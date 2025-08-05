import json
import re
import base64
import logging
import os
from pymongo import MongoClient
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from openai import AsyncAzureOpenAI
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.config import settings
from .models import QuestionRequest, FinalResponse, ChartData
from .llm_orchestrator import create_execution_plan, synthesize_response
from .data_tools import ToolExecutor
from pydantic import BaseModel


router = APIRouter()
logger = logging.getLogger(__name__)

# coleccion de pregruntas
mongo_db = MongoClient(os.getenv("MONGO_URI"))
wisensor_db = mongo_db["wisensor_db"]

# Cliente para Text-to-Speech (TTS)
try:
    tts_client = AsyncAzureOpenAI(
        api_version=settings.azure_openai_tts_api_version,
        azure_endpoint=settings.azure_openai_tts_endpoint,
        api_key=settings.azure_openai_tts_api_key,
    )
except Exception as e:
    tts_client = None
    logger.error(f"No se pudo inicializar el cliente TTS de Azure: {e}")
# chat_router.py
from datetime import datetime

# chat_router.py

def merge_timeseries_data_for_chart(collected_data: dict, plan: dict) -> dict:
    timeseries_keys = [
        step["store_result_as"] for step in plan.get("plan", []) 
        if step.get("tool") == "get_timeseries_data"
    ]

    if not timeseries_keys:
        return collected_data

    all_points = []
    # --- LÓGICA MEJORADA PARA MÚLTIPLES MÉTRICAS ---
    # 1. Recolectar todos los puntos de datos, reconociendo múltiples métricas por registro
    for key in timeseries_keys:
        result = collected_data.get(key, {})
        for item in result.get("data", []):
            fecha = item.get("fecha")
            if not fecha: continue
            
            # Itera sobre todas las posibles métricas en el registro
            for metric_key, value in item.items():
                if metric_key != 'fecha':
                    all_points.append({
                        "fecha": fecha,
                        "metric_name": metric_key,
                        "value": value
                    })

    if not all_points:
        return collected_data

    # 2. Ordenar todos los puntos cronológicamente
    all_points.sort(key=lambda x: x["fecha"])

    # 3. Construir la estructura final del gráfico
    unique_timestamps = sorted(list(set(p["fecha"] for p in all_points)))
    xAxis = [ts.strftime('%Y-%m-%d %H:%M:%S') for ts in unique_timestamps]
    
    unique_metrics = sorted(list(set(p["metric_name"] for p in all_points)))
    
    series = []
    for metric in unique_metrics:
        serie_data = []
        # Crea un mapa de (timestamp -> valor) para esta métrica específica
        points_for_this_metric = {p["fecha"]: p["value"] for p in all_points if p["metric_name"] == metric}
        
        for ts in unique_timestamps:
            serie_data.append(points_for_this_metric.get(ts, None)) # Añade el valor o null
        
        series.append({"name": metric.replace("_", " ").title(), "data": serie_data})

    # --- FIN DE LA LÓGICA MEJORADA ---

    if not series:
        return collected_data

    # Generamos un título dinámico
    center_name = "Centro"
    for key, value in collected_data.items():
        if isinstance(value, dict) and "center_name" in value:
            center_name = value["center_name"]
            break
            
    chart_title = f'Gráfico de {", ".join(unique_metrics).replace("_", " ").title()} para {center_name}'

    collected_data["merged_chart_data"] = {
        "type": "line",
        "title": chart_title,
        "xAxis": xAxis,
        "series": series
    }

    logger.info("Datos de series de tiempo procesados. Eliminando fuentes originales del contexto.")
    for key in timeseries_keys:
        if key in collected_data:
            del collected_data[key]
            
    return collected_data

def limpiar_contexto(data: dict) -> dict:
    contexto = data.get("contexto_previo", [])
    for mensaje in contexto:
        mensaje.pop("audioBase64", None)
    return {
        "user_question": data.get("user_question"),
        "contexto_previo": contexto
    }

def limitar_contexto(contexto_previo: list, max_length: int = 3) -> list:
    # Mientras la longitud sea mayor que max_length, elimina el primer elemento
    while len(contexto_previo) > max_length:
        contexto_previo.pop(0)
    return contexto_previo

@router.post("/analyze-question/", response_model=FinalResponse)
async def analyze_question_endpoint(
    request: QuestionRequest, 
    db: Session = Depends(get_db)):
    
    data_dict = request.dict()
    data_limpio = limpiar_contexto(data_dict)
    
    if "contexto_previo" in data_limpio:
        data_limpio["contexto_previo"] = limitar_contexto(data_limpio["contexto_previo"], 3)
        
    # ETAPA 1: PLANIFICACIÓN
    logger.info(f"Creando plan para la pregunta: '{request.user_question}'")
    plan = await create_execution_plan(request.user_question, request.center_id, data_limpio['contexto_previo'])
    
    if not plan or "error" in plan:
        raise HTTPException(status_code=500, detail=f"No se pudo crear un plan de ejecución válido: {plan.get('details', 'Error desconocido')}")

    if plan.get("plan") and plan["plan"][0].get("tool") == "direct_answer":
        direct_response_text = plan["plan"][0].get("response", "No pude procesar tu saludo, intenta de nuevo.")
        logger.info(f"Respuesta directa generada: {direct_response_text}")
        return FinalResponse(answer=direct_response_text)

    if plan.get("plan") is None:
         raise HTTPException(status_code=500, detail="La IA no generó un plan de acción para esta pregunta.")

    # ETAPA 2: EJECUCIÓN CON LÓGICA DE FALLBACK
    logger.info(f"Ejecutando plan: {plan}")
    executor = ToolExecutor(db_session=db)
    collected_data = {}

    for step in plan["plan"]:
        tool_name = step.get("tool")
        parameters = step.get("parameters", {}).copy() 
        result_key = step.get("store_result_as")
        
        try:
            # --- INICIO DE LA LÓGICA DE REEMPLAZO DE PLACEHOLDERS ---
            for param_key, param_value in parameters.items():
                if isinstance(param_value, str):
                    # Expresión regular para encontrar placeholders como {{...}} o ${...}
                    match = re.match(r'^\$\{(.*)\}$|^\{\{(.*)\}\}$', param_value)
                    if match:
                        # Extrae el contenido del placeholder (ej: "polocuhe_id.center_id")
                        placeholder_content = next((g for g in match.groups() if g is not None), None)
                        if not placeholder_content:
                            raise ValueError(f"No se pudo extraer contenido del placeholder: {param_value}")

                        parts = placeholder_content.split('.')
                        previous_result_key = parts[0] # "polocuhe_id"
                        value_key = parts[1]           # "center_id"

                        # Busca el valor en los datos ya recolectados
                        if previous_result_key in collected_data and value_key in collected_data[previous_result_key]:
                            actual_value = collected_data[previous_result_key][value_key]
                            parameters[param_key] = actual_value # Reemplaza el placeholder con el valor real (ej: 6)
                            logger.info(f"Placeholder '{param_value}' reemplazado con el valor: {actual_value}")
                        else:
                            raise ValueError(f"No se pudo resolver el placeholder: {param_value}. El resultado del paso anterior no está disponible.")
            # --- FIN DE LA LÓGICA DE REEMPLAZO ---

            if hasattr(executor, tool_name):
                tool_method = getattr(executor, tool_name)
                result = tool_method(**parameters)
                collected_data[result_key] = result

                # Tu lógica de fallback (sin cambios)
                if tool_name == "get_timeseries_data" and result.get("count") == 0:
                    logger.info(f"No se encontraron datos para '{result_key}'. Buscando rango disponible...")
                    range_info = executor.get_data_range_summary(
                        source=parameters.get('source'), 
                        center_id=parameters.get('center_id')
                    )
                    collected_data[f"{result_key}_range_info"] = range_info
            else:
                collected_data[result_key] = {"error": f"Herramienta '{tool_name}' no encontrada."}
                
        except Exception as e:
            logger.error(f"Error en el paso '{tool_name}': {e}")
            collected_data[result_key] = {"error": f"Ocurrió un error inesperado al ejecutar '{tool_name}'."}
    
    final_chart_object = None
    user_wants_chart = any(keyword in request.user_question.lower() for keyword in ["grafico", "graficar", "dibuja", "muestra un", "visualiza un"])
    # Solo intentamos procesar y crear un gráfico si el usuario lo pidió
    if user_wants_chart:
        logger.info("El usuario solicitó un gráfico. Iniciando procesamiento de datos para gráfico.")
        
        # Procesamiento de datos de series de tiempo
        collected_data = merge_timeseries_data_for_chart(collected_data, plan)
        if "merged_chart_data" in collected_data:
            logger.info("Creando objeto ChartData desde datos de series de tiempo pre-procesados.")
            final_chart_object = ChartData(**collected_data["merged_chart_data"]) 
        
    # ETAPA 3: SÍNTESIS (La IA genera texto y, a veces, un gráfico de informe)
    logger.info(f"Sintetizando respuesta con datos: {collected_data}")
    raw_synthesis = await synthesize_response(request.user_question, collected_data)

    # Intento 2: Si no teníamos un gráfico de series de tiempo, buscar uno de informe
    if user_wants_chart and final_chart_object is None and isinstance(raw_synthesis, str):
        if final_chart_object is None and isinstance(raw_synthesis, str):
            chart_match = re.search(r'```json\s*({[\s\S]*?})\s*```', raw_synthesis, re.DOTALL)
            if chart_match:
                try:
                    logger.info("Se encontró un JSON de gráfico en la respuesta de la IA. Procesando...")
                    chart_json_str = chart_match.group(1)
                    chart_obj = json.loads(chart_json_str)
                    
                    if 'chart' in chart_obj:
                        # Asignamos el resultado a la misma variable final
                        final_chart_object = ChartData(**chart_obj['chart'])
                        # Limpiamos el texto
                        raw_synthesis = re.sub(r'```json[\s\S]*?```', '', raw_synthesis).strip()
                
                except Exception as e:
                    logger.error(f"Error al parsear el JSON del gráfico del informe: {e}")
                    final_chart_object = None

    final_text = raw_synthesis
    # Generación de audio
    audio_base64 = None
    if tts_client and final_text:
        try:
            audio_response = await tts_client.audio.speech.create(
                input=final_text,
                model=settings.azure_openai_tts_deployment,
                voice="nova",
                response_format="mp3"
            )
            audio_base64 = base64.b64encode(audio_response.content).decode("utf-8")
        except Exception as e:
            logger.error(f"Error al generar audio: {e}")
    logger.info(f"respuesta: {final_text}, chart: {final_chart_object}, audio_base64: {audio_base64}, contexto={collected_data}")
    
    #Almacenar en la base de datos
    wisensor_db["questions"].insert_one(
        {
            "pregunta": request.user_question,
            "respuesta": final_text
        }
    )
    
    return FinalResponse(
        answer=final_text,
        chart=final_chart_object,
        audio_base64=audio_base64,
        debug_context=collected_data
    )


class AudioResponse(BaseModel):
    text: str

@router.post("/analyze-question-audio/")
async def analyze_question_audio(
    request: AudioResponse,
    db: Session = Depends(get_db)
    ):
    final_text = request.text
    if tts_client and final_text:
        try:
            audio_response = await tts_client.audio.speech.create(
                input=final_text,
                model=settings.azure_openai_tts_deployment,
                voice="nova",
                response_format="mp3"
            )
            audio_base64 = base64.b64encode(audio_response.content).decode("utf-8")
        except Exception as e:
            logger.error(f"Error al generar audio: {e}")
            
    return audio_base64