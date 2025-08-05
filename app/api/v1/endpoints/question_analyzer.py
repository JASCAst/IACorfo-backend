# app/routers/analysis_router.py

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, conint
from openai import AsyncAzureOpenAI
import os
import re
import json
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Center

# --- Configuración Inicial ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
load_dotenv()

# --- Modelos de Datos ---
class QuestionRequest(BaseModel):
    user_question: str = Field(..., min_length=5, max_length=500)
    center_id: conint(gt=0)
    analysis_depth: Literal["basic", "detailed", "exhaustive"] = "basic"

class FeedbackModel(BaseModel):
    question_id: str
    rating: conint(ge=1, le=5)
    comments: Optional[str] = None

@dataclass
class DataTool:
    name: str
    keywords: List[str]
    query_fn: callable
    summary_fn: callable
    days: int = 30

# --- Clientes de Servicios Externos ---
try:
    client = AsyncAzureOpenAI(
        api_version=settings.azure_openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
    )

    mongo_client = AsyncIOMotorClient(settings.mongo_uri)
    mongo_db = mongo_client[settings.mongo_db_name]
    analyzed_reports_collection = mongo_db["analyzed_reports"]
    chat_history_collection = mongo_db["chat_history"]
    alimentacion_collection = mongo_db["alimentacion"]
    clima_collection = mongo_db["clima"]
    logger.info("Conexión a servicios exitosa")
except Exception as e:
    logger.error(f"Error de inicialización: {e}")
    raise RuntimeError(f"Error de configuración: {e}") from e

# --- Funciones de Utilidad ---
async def get_center_info(db: Session, center_id: int) -> Dict:
    """Obtiene información estructurada de un centro"""
    center = db.query(Center).filter(Center.id == center_id).first()
    if not center:
        return {}
    return {
        "id": center.id,
        "name": center.name,
        "code": center.code,
        "location": getattr(center, 'location', "No especificada")
    }

def normalize_text(text: str) -> str:
    """Normaliza texto para búsquedas"""
    return text.lower().strip()

# --- Herramientas de Datos ---
async def get_report_analysis(center_id: int, num_reports: int = 1) -> Dict:
    """Obtiene análisis de informes técnicos"""
    try:
        reports = await analyzed_reports_collection.find(
            {"center_id": center_id}
        ).sort("upload_date", -1).limit(num_reports).to_list(num_reports)
        
        if not reports:
            return {"success": False, "error": "No hay informes disponibles"}
            
        return {
            "success": True,
            "data": [{"summary": r.get("summary", ""), "date": r.get("upload_date")} for r in reports],
            "count": len(reports)
        }
    except Exception as e:
        logger.error(f"Error en get_report_analysis: {e}")
        return {"success": False, "error": str(e)}

async def get_alimentacion_data(db: Session, center_id: int, days: int = 30) -> Dict:
    """Obtiene datos resumidos de alimentación"""
    try:
        center_info = await get_center_info(db, center_id)
        if not center_info:
            return {"success": False, "error": "Centro no encontrado"}
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Búsqueda optimizada
        query = {
            "$or": [
                {"codigo_centro": str(center_info["code"])},
                {"nombre_centro": {"$regex": center_info["name"], "$options": "i"}}
            ],
            "fecha": {"$gte": start_date, "$lte": end_date}
        }
        
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": None,
                "avg_racion": {"$avg": "$racion"},
                "total_alimento": {"$sum": "$racion"},
                "count": {"$sum": 1}
            }}
        ]
        
        data = await alimentacion_collection.aggregate(pipeline).to_list(1)
        
        if not data or data[0]['count'] == 0:
            return {
                "success": False, 
                "error": "No hay datos disponibles",
                "center_info": center_info
            }
            
        return {
            "success": True,
            "data": {
                "avg_racion": round(data[0].get("avg_racion", 0), 2),
                "total_alimento": round(data[0].get("total_alimento", 0), 2)
            },
            "timeframe": f"{start_date.date()} a {end_date.date()}",
            "center_info": center_info
        }
    except Exception as e:
        logger.error(f"Error en get_alimentacion_data: {e}")
        return {"success": False, "error": str(e)}

async def get_clima_data(db: Session, center_id: int, days: int = 7) -> Dict:
    """Obtiene datos climáticos resumidos"""
    try:
        center_info = await get_center_info(db, center_id)
        if not center_info:
            return {"success": False, "error": "Centro no encontrado"}
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        query = {
            "codigo_centro": str(center_info["code"]),
            "fecha": {"$gte": start_date, "$lte": end_date}
        }
        
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": None,
                "avg_temperatura": {"$avg": "$temperatura"},
                "avg_oxigeno": {"$avg": "$oxigeno"},
                "count": {"$sum": 1}
            }}
        ]
        
        data = await clima_collection.aggregate(pipeline).to_list(1)
        
        if not data or data[0]['count'] == 0:
            return {
                "success": False, 
                "error": "No hay datos disponibles",
                "center_info": center_info
            }
            
        return {
            "success": True,
            "data": {
                "avg_temperatura": round(data[0].get("avg_temperatura", 0), 2),
                "avg_oxigeno": round(data[0].get("avg_oxigeno", 0), 2)
            },
            "timeframe": f"{start_date.date()} a {end_date.date()}",
            "center_info": center_info
        }
    except Exception as e:
        logger.error(f"Error en get_clima_data: {e}")
        return {"success": False, "error": str(e)}

async def get_centers_info(db: Session) -> Dict:
    """Obtiene información básica de centros"""
    try:
        centers = db.query(Center).all()
        return {
            "success": True,
            "data": [{
                "id": c.id,
                "name": c.name,
                "code": c.code
            } for c in centers],
            "count": len(centers)
        }
    except Exception as e:
        logger.error(f"Error en get_centers_info: {e}")
        return {"success": False, "error": str(e)}

# --- Configuración de Herramientas ---
TOOLS = {
    "report_analysis": DataTool(
        name="report_analysis",
        keywords=["informe", "reporte", "análisis", "documento"],
        query_fn=get_report_analysis,
        summary_fn=lambda d: f"Informes técnicos: {d['count']} disponibles (último: {d['data'][0]['date'].strftime('%Y-%m-%d')})",
        days=365
    ),
    "alimentacion": DataTool(
        name="alimentacion",
        keywords=["alimentación", "comida", "ración", "consumo"],
        query_fn=get_alimentacion_data,
        summary_fn=lambda d: f"Alimentación: {d['data']['avg_racion']}kg promedio (total: {d['data']['total_alimento']}kg)",
        days=30
    ),
    "clima": DataTool(
        name="clima",
        keywords=["clima", "temperatura", "oxígeno", "ph"],
        query_fn=get_clima_data,
        summary_fn=lambda d: f"Clima: Temp. {d['data']['avg_temperatura']}°C, Oxígeno {d['data']['avg_oxigeno']}mg/L",
        days=7
    ),
    "centers": DataTool(
        name="centers",
        keywords=["centro", "granja", "ubicación"],
        query_fn=get_centers_info,
        summary_fn=lambda d: f"Centros disponibles: {d['count']}",
        days=0
    )
}

def select_tools_v2(question: str) -> List[str]:
    """Selección inteligente de herramientas con priorización"""
    question = normalize_text(question)
    selected = []
    
    # Priorizar herramientas específicas para preguntas técnicas
    if "informe" in question or "reporte" in question:
        selected.append("report_analysis")
    
    # Detección de necesidades de datos
    if any(kw in question for kw in ["alimentación", "ración", "comida"]):
        selected.append("alimentacion")
    if any(kw in question for kw in ["clima", "temperatura", "oxígeno"]):
        selected.append("clima")
    
    # Siempre incluir centers si se menciona un centro
    if any(kw in question for kw in ["centro", "granja"]):
        if "centers" not in selected:
            selected.append("centers")
    
    return selected or ["centers"]

async def prepare_context(tool_results: Dict, request: QuestionRequest) -> str:
    """Prepara un contexto optimizado para OpenAI"""
    context_parts = []
    center_info = None
    
    for tool, data in tool_results.items():
        if not data.get('success'):
            context_parts.append(f"{tool.upper()}: No hay datos disponibles")
            continue
        
        if tool == "report_analysis":
            reports = data['data']
            summary = f"INFORMES TÉCNICOS ({data['count']} disponibles):\n"
            summary += "\n".join([f"- {r['date'].strftime('%Y-%m-%d')}: {r['summary'][:100]}..." for r in reports[:3]])
            context_parts.append(summary)
        
        elif tool == "alimentacion":
            center_info = data.get('center_info')
            context_parts.append(
                f"ALIMENTACIÓN ({data.get('timeframe')}):\n"
                f"- Ración promedio: {data['data']['avg_racion']} kg\n"
                f"- Consumo total: {data['data']['total_alimento']} kg"
            )
        
        elif tool == "clima":
            center_info = center_info or data.get('center_info')
            context_parts.append(
                f"CLIMA ({data.get('timeframe')}):\n"
                f"- Temperatura promedio: {data['data']['avg_temperatura']}°C\n"
                f"- Oxígeno promedio: {data['data']['avg_oxigeno']} mg/L"
            )
        
        elif tool == "centers":
            context_parts.append(
                f"CENTROS DISPONIBLES: {data['count']} centros registrados"
            )
    
    # Añadir información del centro si está disponible
    if center_info:
        context_parts.insert(0, 
            f"CENTRO ACTUAL:\n"
            f"- Nombre: {center_info['name']}\n"
            f"- Código: {center_info['code']}\n"
            f"- Ubicación: {center_info.get('location', 'No especificada')}"
        )
    
    return "\n\n".join(context_parts)

def get_system_prompt(request: QuestionRequest) -> str:
    """Genera un prompt adaptado al nivel de análisis"""
    base_prompt = """Eres AquaExpert, un asistente especializado en acuicultura. Sigue estas reglas:

1. CONTEXTO: Tienes acceso a datos de centros de cultivo
2. FORMATO: Responde en español, con estilo profesional pero claro
3. PRECISIÓN: Usa solo los datos proporcionados
4. ESTRUCTURA:
   - Breve introducción
   - Datos relevantes
   - Conclusión o recomendación (si aplica)"""
    
    if request.analysis_depth == "detailed":
        base_prompt += "\n\nINCLUYE:\n- Detalles técnicos\n- Comparaciones\n- Tendencias"
    elif request.analysis_depth == "exhaustive":
        base_prompt += "\n\nINCLUYE:\n- Análisis completo\n- Posibles causas\n- Recomendaciones técnicas\n- Referencias a estándares del sector"
    
    return base_prompt

# --- Endpoint Optimizado ---
@router.post("/analyze-question/")
async def analyze_question(
    request: QuestionRequest, 
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Endpoint optimizado para análisis de preguntas"""
    start_time = datetime.utcnow()
    analysis_id = str(uuid.uuid4())
    
    try:
        # 1. Selección inteligente de herramientas
        selected_tools = select_tools_v2(request.user_question)
        logger.info(f"Herramientas seleccionadas: {selected_tools}")
        
        # 2. Obtención paralela de datos
        tasks = []
        for tool in selected_tools:
            tool_config = TOOLS.get(tool)
            if tool_config:
                # Manejo especial para centers que no necesita center_id ni days
                if tool == "centers":
                    tasks.append(tool_config.query_fn(db))
                else:
                    tasks.append(tool_config.query_fn(db, request.center_id, tool_config.days))
        
        tool_results = dict(zip(selected_tools, await asyncio.gather(*tasks)))
        
        # 3. Preparación de contexto optimizado
        context = await prepare_context(tool_results, request)
        
        # 4. Configuración adaptativa para OpenAI
        max_tokens = {
            "basic": 800,
            "detailed": 1200,
            "exhaustive": 1500
        }.get(request.analysis_depth, 1000)
        
        temperature = 0.3 if any(kw in request.user_question.lower() for kw in ["técnico", "técnica", "problema"]) else 0.7
        
        # 5. Llamada a OpenAI
        response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": get_system_prompt(request)},
                {"role": "user", "content": f"Pregunta: {request.user_question}\n\nDatos:\n{context}"}
            ],
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        answer = response.choices[0].message.content
        usage = response.usage
        
        # 6. Registro optimizado en historial
        history_record = {
            "analysis_id": analysis_id,
            "timestamp": datetime.utcnow(),
            "question": request.user_question,
            "answer": answer,
            "center_id": request.center_id,
            "analysis_depth": request.analysis_depth,
            "tools_used": selected_tools,
            "token_usage": {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
                "total": usage.total_tokens
            },
            "processing_time_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000)
        }
        
        await chat_history_collection.insert_one(history_record)
        
        return {
            "success": True,
            "analysis_id": analysis_id,
            "answer": answer,
            "metadata": {
                "tools_used": selected_tools,
                "token_usage": history_record["token_usage"],
                "processing_time": f"{history_record['processing_time_ms']}ms"
            }
        }
        
    except Exception as e:
        logger.error(f"Error en analyze_question: {e}")
        await chat_history_collection.insert_one({
            "analysis_id": analysis_id,
            "timestamp": datetime.utcnow(),
            "error": str(e),
            "question": request.user_question,
            "center_id": request.center_id
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando la pregunta: {str(e)}"
        )

# --- Sistema de Feedback (optimizado) ---
@router.post("/feedback/optimized")
async def submit_feedback_optimized(feedback: FeedbackModel):
    """Endpoint optimizado para feedback"""
    try:
        update_data = {
            "feedback": feedback.dict(),
            "feedback_timestamp": datetime.utcnow(),
            "processed": False
        }
        
        result = await chat_history_collection.update_one(
            {"analysis_id": feedback.question_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
            
        return {"success": True, "message": "Feedback registrado para análisis"}
    except Exception as e:
        logger.error(f"Error guardando feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error procesando feedback"
        )

@router.on_event("startup")
async def startup_tasks():
    """Tareas de inicio optimizadas"""
    logger.info("Servicio de análisis optimizado listo")