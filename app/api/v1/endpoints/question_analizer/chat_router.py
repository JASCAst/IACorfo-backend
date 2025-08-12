import json
import re
import base64
import logging
import os
import difflib
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
    """
    Combina múltiples resultados de series de tiempo en un solo objeto de gráfico,
    creando una serie distinta para cada combinación de métrica y centro de origen.
    """
    # 1. Identificar todos los resultados que son de series de tiempo
    timeseries_keys = [
        step["store_result_as"] for step in plan.get("plan", []) 
        if step.get("tool") == "get_timeseries_data"
    ]

    if not timeseries_keys:
        return collected_data

    # 2. Recolectar todos los puntos de datos, pero conservando su origen
    all_points = []
    center_names_map = {} # Para guardar los nombres bonitos de los centros

    for key in timeseries_keys: # ej: "temperatura_pirquen"
        result = collected_data.get(key, {})
        if not result or not result.get("data"):
            continue

        # --- LÓGICA CLAVE: ENCONTRAR EL NOMBRE DEL CENTRO ---
        # Extraemos el nombre del centro de la clave, ej: "pirquen" de "temperatura_pirquen"
        # Esto es una suposición, pero funciona para planes bien nombrados.
        try:
            center_alias = key.split('_')[-1]
            # Buscamos en el contexto el resultado de 'get_center_id_by_name' que corresponde a ese alias
            center_info_key = f"{center_alias}_id" # ej: "pirquen_id"
            if center_info_key in collected_data:
                center_names_map[key] = collected_data[center_info_key].get("center_name", center_alias.title())
            else:
                center_names_map[key] = center_alias.title()
        except:
            center_names_map[key] = key # Fallback

        # --- FIN LÓGICA CLAVE ---

        for item in result.get("data", []):
            fecha = item.get("fecha")
            if not fecha: continue
            
            for metric_key, value in item.items():
                if metric_key != 'fecha':
                    all_points.append({
                        "fecha": fecha,
                        "origin_key": key,        # ej: "temperatura_pirquen"
                        "metric_name": metric_key, # ej: "temperatura"
                        "value": value
                    })

    if not all_points:
        return collected_data

    # 3. Construir la estructura del gráfico
    unique_timestamps = sorted(list(set(p["fecha"] for p in all_points)))
    xAxis = [ts.strftime('%Y-%m-%d %H:%M:%S') for ts in unique_timestamps]
    
    # Identificamos las series únicas (ej: ('temperatura_pirquen', 'temperatura'))
    unique_series_defs = sorted(list(set((p["origin_key"], p["metric_name"]) for p in all_points)))
    
    series_data = []
    chart_metric_names = []
    chart_center_names = set()

    for origin_key, metric_name in unique_series_defs:
        # Crear un nombre descriptivo para la leyenda del gráfico
        center_display_name = center_names_map.get(origin_key, origin_key)
        metric_display_name = metric_name.replace("_", " ").title()
        
        series_name = f"{metric_display_name} ({center_display_name})" # ej: "Temperatura (Centro Pirquen)"
        
        # Guardar nombres para el título del gráfico
        if metric_display_name not in chart_metric_names:
            chart_metric_names.append(metric_display_name)
        chart_center_names.add(center_display_name)

        # Filtrar los puntos que pertenecen solo a esta serie
        points_for_this_series = {
            p["fecha"]: p["value"] for p in all_points 
            if p["origin_key"] == origin_key and p["metric_name"] == metric_name
        }
        
        current_serie_points = []
        for ts in unique_timestamps:
            current_serie_points.append(points_for_this_series.get(ts, None)) 
        
        series_data.append({"name": series_name, "data": current_serie_points})

    if not series_data:
        return collected_data

    # 4. Generar un título dinámico y el objeto final del gráfico
    title = f'Comparativa de {", ".join(chart_metric_names)} en {", ".join(sorted(list(chart_center_names)))}'

    collected_data["merged_chart_data"] = {
        "type": "line",
        "title": title,
        "xAxis": xAxis,
        "series": series_data
    }

    # 5. Limpiar el contexto para no pasarlo al sintetizador
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

def limitar_contexto(contexto_previo: list, max_length: int = 6) -> list:
    # Mientras la longitud sea mayor que max_length, elimina el primer elemento
    while len(contexto_previo) > max_length:
        contexto_previo.pop(0)
    return contexto_previo

def contiene_palabra_similar(texto, palabras_clave, umbral=0.8):
    palabras = texto.lower().split()
    for palabra in palabras:
        coincidencias = difflib.get_close_matches(palabra, palabras_clave, cutoff=umbral)
        if coincidencias:
            return True
    return False

@router.post("/analyze-question/")
async def analyze_question_endpoint(
    request: QuestionRequest, 
    db: Session = Depends(get_db)):
    
    data_dict = request.dict()
    data_limpio = limpiar_contexto(data_dict)
    
    if "contexto_previo" in data_limpio:
        data_limpio["contexto_previo"] = limitar_contexto(data_limpio["contexto_previo"], 6)
        
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
                            #Agregar estado a la respuesta
            
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
    user_wants_chart = contiene_palabra_similar(
                        request.user_question,
                        ["grafico", "graficar", "dibuja", "muestra", "visualiza"]
                    )
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
    # if tts_client and final_text:
    #     try:
    #         audio_response = await tts_client.audio.speech.create(
    #             input=final_text,
    #             model=settings.azure_openai_tts_deployment,
    #             voice="nova",
    #             response_format="mp3"
    #         )
    #         audio_base64 = base64.b64encode(audio_response.content).decode("utf-8")
    #     except Exception as e:
    #         logger.error(f"Error al generar audio: {e}")
    # logger.info(f"respuesta: {final_text}, chart: {final_chart_object}")
    
    #Almacenar en la base de datos
    wisensor_db["questions"].insert_one(
        {
            "pregunta": request.user_question,
            "respuesta": final_text
        }
    )
    
    #si collect_data contiene pirquen_id, entonces se ha pedido el informe de pirquen
    if "polocuhe_id" in collected_data and "pirquen_id" in collected_data:
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
                                            "clima" : "lluvioso"
                                        }
    elif "polocuhe_id" in collected_data:
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
                                            "clima": "soleado"
                                        }
    elif "pirquen_id" in collected_data:
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
                                            "clima": "soleado"
                                        }
    else:
        collected_data["coordendadas"] = None
        
    return FinalResponse(
        answer=final_text,
        chart=final_chart_object, 
        # audio_base64=final_text,
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
