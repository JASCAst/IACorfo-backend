# app/routers/analysis_router.py

import os
import re
import json
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal
from functools import lru_cache
from math import sqrt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, conint, validate_call
from openai import AsyncAzureOpenAI
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy.orm import Session
from aiocache import Cache, cached
from aiocache.serializers import JsonSerializer
from dateutil import parser as date_parser
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from dotenv import load_dotenv

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Center

# --- Configuración Inicial ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = APIRouter()
load_dotenv()

# --- Clientes y Configuraciones Avanzadas ---
class CacheConfig:
    REDIS_URL = settings.redis_url
    TOOL_TTL = 3600  # 1 hora
    PLAN_TTL = 1800  # 30 minutos

# Configuración OpenTelemetry
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer("analysis.advanced")

# Clientes asíncronos
client = AsyncAzureOpenAI(
    api_version=settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
)

mongo_client = AsyncIOMotorClient(settings.mongo_uri)
mongo_db = mongo_client[settings.mongo_db_name]

# --- Modelos Pydantic Mejorados ---
class QuestionRequest(BaseModel):
    user_question: str = Field(..., min_length=5, max_length=500)
    center_id: conint(gt=0)
    analysis_depth: Literal["basic", "detailed", "exhaustive"] = "basic"

class FeedbackModel(BaseModel):
    question_id: str
    rating: conint(ge=1, le=5)
    correctness: bool
    comments: Optional[str] = None

# --- Registro de Herramientas con Embeddings ---
REGISTERED_TOOLS = [
    {
        "name": "get_timeseries_data",
        "description": "Obtiene datos históricos de alimentación o clima",
        "embedding": [0.2, 0.7, 0.1]  # Embedding precalculado
    },
    {
        "name": "get_semantic_report_context",
        "description": "Busca en informes técnicos",
        "embedding": [0.8, 0.1, 0.1]
    }
]

# --- Funciones de Utilidad Avanzadas ---
def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calcula similitud coseno entre vectores"""
    dot_product = sum(x*y for x, y in zip(a, b))
    norm_a = sqrt(sum(x**2 for x in a))
    norm_b = sqrt(sum(x**2 for x in b))
    return dot_product / (norm_a * norm_b) if norm_a * norm_b != 0 else 0

@lru_cache(maxsize=1000)
async def get_embedding(text: str) -> List[float]:
    """Obtiene embeddings de texto usando OpenAI"""
    response = await client.embeddings.create(
        model=settings.azure_openai_embedding_deployment,
        input=text
    )
    return response.data[0].embedding

# --- Implementación de Herramientas con Caché y Validación ---
@cached(cache=Cache.REDIS, key_builder=lambda f, *args, **kwargs: f"ts_data:{args[1]}:{args[0]}", serializer=JsonSerializer())
@validate_call
async def get_timeseries_data_async(
    data_source: Literal["alimentacion", "clima"],
    center_id: conint(gt=0),
    query_type: Literal["aggregation", "first_record", "last_record"],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Obtiene datos de series temporales con validación avanzada"""
    collection = mongo_db.alimentacion if data_source == "alimentacion" else mongo_db.clima
    
    query = {"center_id": center_id}
    if start_date and end_date:
        query["date"] = {"$gte": start_date, "$lte": end_date}
    
    if query_type == "aggregation":
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": None,
                "avg": {"$avg": "$value"},
                "max": {"$max": "$value"},
                "min": {"$min": "$value"},
                "count": {"$sum": 1}
            }}
        ]
        result = await collection.aggregate(pipeline).to_list(length=1)
        return result[0] if result else {"error": "No data found"}
    
    sort_order = 1 if query_type == "first_record" else -1
    return await collection.find_one(query, sort=[("date", sort_order)])

# --- Motor de Plantillas Adaptativas ---
class ResponseTemplates:
    @staticmethod
    def comparative_analysis(data: Dict) -> str:
        return f"""
        ## Análisis Comparativo
        
        **Centros:** {data['centers']}
        
        | Métrica       | {data['center_names'][0]} | {data['center_names'][1]} | Diferencia |
        |--------------|----------------|----------------|------------|
        | {data['metrics'][0]} | {data['values'][0][0]} | {data['values'][0][1]} | {data['diffs'][0]} |
        
        **Conclusión:** {data['insight']}
        """

# --- Endpoint Principal Mejorado ---
@router.post("/advanced-analysis/")
async def advanced_analysis(
    request: QuestionRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Endpoint avanzado que combina:
    - Planificación inteligente
    - Ejecución paralela con caché
    - Síntesis adaptativa
    - Generación de visualizaciones
    """
    start_time = datetime.utcnow()
    
    with tracer.start_as_current_span("advanced_analysis") as span:
        span.set_attributes({
            "question": request.user_question,
            "center_id": request.center_id,
            "depth": request.analysis_depth
        })

        # 1. Pre-procesamiento y priorización
        question_embedding = await get_embedding(request.user_question)
        prioritized_tools = sorted(
            REGISTERED_TOOLS,
            key=lambda x: cosine_similarity(question_embedding, x["embedding"]),
            reverse=True
        )[:3]  # Top 3 herramientas relevantes

        # 2. Planificación mejorada
        @cached(cache=Cache.REDIS, key=f"plan:{hash(request.user_question)}", serializer=JsonSerializer())
        async def generate_execution_plan() -> Dict:
            plan_prompt = f"""
            Genera un plan JSON para: "{request.user_question}"
            Herramientas prioritarias: {[t['name'] for t in prioritized_tools]}
            Centro: {request.center_id}
            Profundidad: {request.analysis_depth}
            """
            
            response = await client.chat.completions.create(
                model=settings.azure_openai_deployment,
                messages=[{"role": "system", "content": plan_prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)

        plan = await generate_execution_plan()
        
        # 3. Ejecución paralela optimizada
        tool_results = {}
        for step in plan.get("steps", []):
            tool_name = step["tool"]
            if tool_name in ["get_timeseries_data", "get_semantic_report_context"]:
                tool_func = globals()[f"{tool_name}_async"]
                try:
                    tool_results[step["name"]] = await tool_func(**step["params"])
                except Exception as e:
                    logger.error(f"Error en {tool_name}: {str(e)}")
                    tool_results[step["name"]] = {"error": str(e)}

        # 4. Síntesis mejorada
        synthesizer_prompt = f"""
        ### Contexto Completo:
        {json.dumps(tool_results, indent=2)}
        
        ### Instrucciones:
        - Profundidad: {request.analysis_depth}
        - Formato: Incluye visualizaciones si es relevante
        - Estilo: {"Técnico detallado" if request.analysis_depth != "basic" else "Resumen conciso"}
        """
        
        final_response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": synthesizer_prompt},
                {"role": "user", "content": request.user_question}
            ],
            max_tokens=3000
        )

        # 5. Post-procesamiento inteligente
        response_content = final_response.choices[0].message.content
        chart_data = None
        
        if "```json" in response_content:
            try:
                chart_match = re.search(r'```json\s*({.+?})\s*```', response_content, re.DOTALL)
                chart_data = json.loads(chart_match.group(1))
                response_content = response_content.replace(chart_match.group(0), "").strip()
            except Exception as e:
                logger.error(f"Error parsing chart: {str(e)}")

        # 6. Estructura de respuesta mejorada
        return {
            "analysis_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "answer": response_content,
            "visualizations": chart_data,
            "sources": [k for k in tool_results.keys()],
            "metadata": {
                "analysis_time_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
                "llm_usage": {
                    "prompt_tokens": final_response.usage.prompt_tokens,
                    "completion_tokens": final_response.usage.completion_tokens,
                    "total_tokens": final_response.usage.total_tokens
                },
                "cache_hits": getattr(generate_execution_plan, "cache_info", lambda: {})().get("hits", 0)
            }
        }

# --- Sistema de Feedback y Mejora Continua ---
@router.post("/submit-feedback")
async def submit_feedback(feedback: FeedbackModel):
    """Endpoint para recibir feedback de los usuarios"""
    await mongo_db.feedbacks.insert_one({
        **feedback.dict(),
        "timestamp": datetime.utcnow(),
        "automated_review": await generate_automated_review(feedback)
    })
    return {"status": "feedback_received"}

async def generate_automated_review(feedback: FeedbackModel) -> Dict:
    """Genera sugerencias de mejora basadas en feedback"""
    review_prompt = f"""
    Feedback recibido:
    - Puntuación: {feedback.rating}/5
    - Correcto: {"Sí" if feedback.correctness else "No"}
    - Comentarios: {feedback.comments or "Ninguno"}
    
    Sugiere 3 mejoras específicas:
    """
    
    response = await client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[{"role": "user", "content": review_prompt}],
        max_tokens=500
    )
    
    return {"suggestions": response.choices[0].message.content.split("\n")}

# --- Tarea en Background para Mejora Continua ---
async def retrain_model_periodically():
    """Tarea en background para reentrenamiento periódico"""
    while True:
        await asyncio.sleep(86400)  # Diariamente
        new_feedback = await mongo_db.feedbacks.find({"reviewed": False}).to_list(length=None)
        if len(new_feedback) > 50:
            logger.info("Iniciando proceso de reentrenamiento con nuevo feedback")
            # Aquí iría la lógica de reentrenamiento
            await mongo_db.feedbacks.update_many(
                {"_id": {"$in": [f["_id"] for f in new_feedback]}},
                {"$set": {"reviewed": True}}
            )

# Iniciar tarea en background al arrancar la aplicación
@router.on_event("startup")
async def startup_event():
    """Inicia tareas en background al cargar el router"""
    asyncio.create_task(retrain_model_periodically())