# app/chat/chat_router.py

import json
import re
import base64
import logging
from pymongo import MongoClient
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from openai import AsyncAzureOpenAI
from app.core.database import get_db
from app.core.config import settings
from .models import QuestionRequest, FinalResponse, ChartData
from .llm_orchestrator import create_execution_plan, synthesize_response
from .data_tools import ToolExecutor
from typing import List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# Conexión a MongoDB para el historial de preguntas
try:
    mongo_db_client = MongoClient(settings.mongo_uri)
    wisensor_db = mongo_db_client[settings.mongo_db_name]
    questions_collection = wisensor_db["questions_history"]
except Exception as e:
    logger.error(f"No se pudo conectar a MongoDB para el historial: {e}")
    questions_collection = None

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

def clean_context(context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Elimina datos pesados como audio del contexto para no sobrecargar los prompts."""
    if not context:
        return []
    clean = []
    for message in context:
        msg_copy = message.copy()
        msg_copy.pop("audioBase64", None)
        msg_copy.pop("debug_context", None)
        clean.append(msg_copy)
    return clean
def limpiar_contexto(data: dict) -> dict:
    contexto = data.get("contexto_previo", [])
    for mensaje in contexto:
        mensaje.pop("audioBase64", None)
    return {
        "user_question": data.get("user_question"),
        "contexto_previo": contexto
    }

def limitar_contexto(contexto_previo: list, max_length: int = 6) -> list:
    # Mientras la longitud sea mayor que max_length, elimina el primer elemento
    while len(contexto_previo) > max_length:
        contexto_previo.pop(0)
    return contexto_previo

def clima_simple(
    json_data, 
    umbral_lluvia=1.0, 
    umbral_llovizna=1.0,
    usar_viento=True, 
    viento_fuerte=20.0, 
    temp_fresca=12.0
    ):
    
    segunda_clave = list(json_data.keys())[1]
    registro = json_data[segunda_clave]["data"]
    
    if not registro:
        return None
    registro = registro[0]

    precip = float(registro.get("precipitacion", 0) or 0)
    temp = float(registro.get("temperatura", registro.get("temperatura_maxima", 0)) or 0)
    viento = float(registro.get("viento", 0) or 0)

    if precip >= umbral_lluvia:
        return "lluvioso"
    elif 0 < precip < umbral_llovizna:
        return "nublado"

    estado = "soleado"

    if usar_viento and viento >= viento_fuerte and temp <= temp_fresca:
        estado = "nublado"

    return "nublado"

@router.post("/analyze-question/", response_model=FinalResponse)
async def analyze_question_endpoint(request: QuestionRequest, db: Session = Depends(get_db)):
    
    data_dict = request.dict()
    data_limpio = limpiar_contexto(data_dict)
    if "contexto_previo" in data_limpio:
        data_limpio["contexto_previo"] = limitar_contexto(data_limpio["contexto_previo"], 6)

    logger.info(f"Creando plan para la pregunta: '{request.user_question}'")
    plan = await create_execution_plan(request.user_question, request.center_id, data_limpio["contexto_previo"])
    
    if not plan or "plan" not in plan:
        error_detail = plan.get('details', 'Error desconocido al generar el plan.')
        raise HTTPException(status_code=500, detail=f"No se pudo crear un plan de ejecución: {error_detail}")

    collected_data = {}
    executor = ToolExecutor(db_session=db)

    # ETAPA 2: EJECUCIÓN
    logger.info(f"Ejecutando plan: {json.dumps(plan, indent=2)}")
    for step in plan.get("plan", []):
        tool_name = step.get("tool")
        parameters = step.get("parameters", {}).copy()
        result_key = step.get("store_result_as")

        if not all([tool_name, result_key]):
            logger.warning(f"Paso de plan inválido, omitiendo: {step}")
            continue

        try:
            
            for param_key, param_value in parameters.items():
                
                # Caso 1: El valor es un string simple
                if isinstance(param_value, str):
                    match = re.match(r'^\$\{(.*)\.(.*)\}$', param_value)
                    if match:
                        prev_step_key, value_key = match.groups()
                        if prev_step_key in collected_data and value_key in collected_data[prev_step_key]:
                            parameters[param_key] = collected_data[prev_step_key][value_key]
                        else:
                            raise ValueError(f"No se pudo resolver el placeholder: {param_value}")
                
                # Caso 2: El valor es una lista que puede contener placeholders
                elif isinstance(param_value, list):
                    processed_list = []
                    for item in param_value:
                        if isinstance(item, str):
                            match = re.match(r'^\$\{(.*)\.(.*)\}$', item)
                            if match:
                                prev_step_key, value_key = match.groups()
                                if prev_step_key in collected_data and value_key in collected_data[prev_step_key]:
                                    processed_list.append(collected_data[prev_step_key][value_key])
                                else:
                                    raise ValueError(f"No se pudo resolver el placeholder en la lista: {item}")
                            else:
                                processed_list.append(item) 
                        else:
                            processed_list.append(item) 
                    parameters[param_key] = processed_list

            # Ejecución de la herramienta
            if hasattr(executor, tool_name):
                tool_method = getattr(executor, tool_name)
                result = tool_method(**parameters)
                collected_data[result_key] = result

                is_data_tool = tool_name in ["get_timeseries_data", "correlate_timeseries_data", "get_monthly_aggregation"]
                if is_data_tool and result.get("count") == 0 and "center_id" in parameters:
                    logger.info(f"'{tool_name}' no encontró datos. Buscando rango de fechas disponible...")
                    source = parameters.get('source') or parameters.get('primary_source', 'clima')
                    if source:
                        range_info = executor.get_data_range_for_source(center_id=parameters['center_id'], source=source)
                        collected_data[f"{result_key}_available_range"] = range_info

            elif tool_name == "direct_answer":
                collected_data[result_key] = {"answer": parameters.get("response", "No pude procesar tu solicitud.")}
            else:
                raise AttributeError(f"Herramienta '{tool_name}' no encontrada.")

        except Exception as e:
            logger.error(f"Error en el paso '{tool_name}': {e}", exc_info=True)
            collected_data[result_key] = {"error": f"Falló la ejecución de la herramienta '{tool_name}'."}

    logger.info(f"Sintetizando respuesta con datos: {json.dumps(collected_data, indent=2, default=str)}")
    raw_synthesis = await synthesize_response(request.user_question, collected_data)

    final_text = raw_synthesis
    final_chart_object = None

    chart_match = re.search(r'```json\s*({[\s\S]*?})\s*```', raw_synthesis, re.DOTALL)
    if chart_match:
        try:
            chart_json_str = chart_match.group(1)
            chart_obj = json.loads(chart_json_str)
            if 'chart' in chart_obj:
                final_chart_object = ChartData(**chart_obj['chart'])
                final_text = re.sub(r'```json[\s\S]*?```', '', final_text).strip()
        except Exception as e:
            logger.error(f"Error al procesar el JSON del gráfico de la IA: {e}")
            final_chart_object = None
            
    if questions_collection is not None:
        questions_collection.insert_one({
            "question": request.user_question,
            "answer": final_text,
            "timestamp": datetime.now()
        })
        
    def estructura_clima_1_centros(collected_data):
        #restructurar json
        primera_clave = list(collected_data.keys())[0]
        segunda_clave = list(collected_data.keys())[1]
        collected_data["centros"] = [collected_data[primera_clave]]
        collected_data["datos_centros"] = [collected_data[segunda_clave]]
        
        #eliminar datos de clima
        del collected_data[primera_clave]
        del collected_data[segunda_clave]
        
    def estructura_clima_2_centros(collected_data):
        #restructurar json
        primera_clave = list(collected_data.keys())[0]
        segunda_clave = list(collected_data.keys())[1]
        tercera_clave = list(collected_data.keys())[2]
        cuarta_clave = list(collected_data.keys())[3]
        
        #agregar datos de clima
        collected_data["centros"] = [collected_data[primera_clave],[collected_data[segunda_clave]]]
        collected_data["datos_centro"] = [collected_data[tercera_clave],[collected_data[cuarta_clave]]]
        
        #eliminar datos de clima
        del collected_data[primera_clave]
        del collected_data[segunda_clave]
        del collected_data[tercera_clave]
        del collected_data[cuarta_clave]
        
    if "polocuhe_info" in collected_data and "pirquen_info" in collected_data:
        collected_data["coordendadas"] =  {
                                            "id": "5",
                                            "name": "Polocuhe y Pirquen",
                                            "coordinates": [
                                                [-42.1163425, -73.4443599],
                                                [-42.1320328, -73.4319801],
                                                [-42.1217836, -73.4099809],
                                                [-42.1083699, -73.4234658],
                                            ],
                                            "color": "blue",
                                            "zoom": 8,
                                            "clima" : "soleado"
                                        }
        estructura_clima_2_centros(collected_data)
    elif "polocuhe_info" in collected_data:
        collected_data["coordendadas"] =  {
                                            "id": "5",
                                            "name": "Polocuhe",
                                            "coordinates": [
                                                [-42.3076836, -73.3845731],
                                                [-42.5103388, -73.3871473],
                                                [-42.5192116, -73.0835920],
                                                [-42.3167438, -73.0761471],
                                            ],
                                            "color": "blue",
                                            "zoom": 11,
                                            "clima": clima_simple(collected_data)
                                        }
        estructura_clima_1_centros(collected_data)
    elif "pirquen_info" in collected_data:
        collected_data["coordendadas"] =  {
                                            "id": "4",
                                            "name": "Pirquen",
                                            "coordinates": [
                                                [-42.1163425, -73.4443599],
                                                [-42.1320328, -73.4319801],
                                                [-42.1217836, -73.4099809],
                                                [-42.1083699, -73.4234658],
                                            ],
                                            "color": "green",
                                            "zoom": 13,
                                            "clima": clima_simple(collected_data)
                                        }
        estructura_clima_1_centros(collected_data)
    else:
        collected_data["coordendadas"] = None
        
    return FinalResponse(
        answer=final_text,
        chart=final_chart_object,
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
            
    return {
            "audio_base64": audio_base64
            }
    
@router.get("/datos-centros")
async def get_centers_data(
    db: Session = Depends(get_db)
):
    centros = ToolExecutor._get_all_centers(db)
    # recorrer y construir el objeto
    centers = []
    for center in centros:
        if center.canonical_code == "102":
            centers.append({
                            "id": center.id,
                            "name": "Polocuhe",
                            "coordinates": [
                                [-42.3076836, -73.3845731],
                                [-42.5103388, -73.3871473],
                                [-42.5192116, -73.0835920],
                                [-42.3167438, -73.0761471],
                            ],
                            "color": "blue",
                            "clima": "lluvioso"
                        })
        elif center.canonical_code == "10934444":
            centers.append({
                            "id": center.id,
                            "name": "Pirquen",
                            "coordinates": [
                                [-42.1163425, -73.4443599],
                                [-42.1320328, -73.4319801],
                                [-42.1217836, -73.4099809],
                                [-42.1083699, -73.4234658],
                            ],
                            "color": "green",
                            "clima": "soleado"
                        })
        else: 
            centers.append({
                "id": center.id,
                "name": center.canonical_name,
                "coordinates": [[center.latitud, center.longitud]],
                "color": "gray",
                "clima" : "lluvioso"
            })
    return centers


from fastapi.responses import StreamingResponse
import io

@router.post("/analyze-question-audio-streaming/")
async def analyze_question_audio_streaming(
    request: AudioResponse,
    db: Session = Depends(get_db)
):
    final_text = request.text
    if not final_text:
        return {"error": "Texto no proporcionado"}, 400

    try:
        audio_response = await tts_client.audio.speech.create(
            input=final_text,
            model=settings.azure_openai_tts_deployment,
            voice="nova",
            response_format="mp3"
        )

        # Generador síncrono
        def audio_streamer():
            for chunk in audio_response.iter_bytes(chunk_size=1024):
                yield chunk

        return StreamingResponse(audio_streamer(), media_type="audio/mpeg")

    except Exception as e:
        logger.error(f"Error al generar audio en streaming: {e}")
        return {"error": "No se pudo generar el audio"}, 500