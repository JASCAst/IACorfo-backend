from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from openai import AzureOpenAI
import os
from dotenv import load_dotenv
from app.core.config import settings
from pymongo import MongoClient
from typing import Optional, List, Dict, Any
import json
import logging
from datetime import datetime
import re # <-- Importar para detección de preguntas simples
# --- NUEVO: Importar SQLAlchemy y modelo Center ---
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Center
import base64
from dateutil.relativedelta import relativedelta
from dateutil import parser as date_parser
import calendar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Cargar variables de entorno si no están ya cargadas
load_dotenv()

# Configurar el cliente de Azure OpenAI
client = AzureOpenAI(
    api_version=settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    http_client=None
)

# Cliente de OpenAI para TTS (usa las credenciales TTS independientes)
tts_client = AzureOpenAI(
    api_version=settings.azure_openai_tts_api_version,
    azure_endpoint=settings.azure_openai_tts_endpoint,
    api_key=settings.azure_openai_tts_api_key,
    http_client=None
)

# Configurar la conexión a MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://10.20.7.102:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "wisensor_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "analyzed_reports")
MONGO_CHAT_HISTORY_COLLECTION_NAME = os.getenv("MONGO_CHAT_HISTORY_COLLECTION_NAME", "chat_history")
MONGO_CENTERS_COLLECTION_NAME = os.getenv("MONGO_CENTERS_COLLECTION_NAME", "centers")
MONGO_ALIMENTACION_COLLECTION_NAME = os.getenv("MONGO_ALIMENTACION_COLLECTION_NAME", "alimentacion")
MONGO_CLIMA_COLLECTION_NAME = os.getenv("MONGO_CLIMA_COLLECTION_NAME", "clima")


try:
    mongo_client = MongoClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB_NAME]
    analyzed_reports_collection = mongo_db[MONGO_COLLECTION_NAME]
    chat_history_collection = mongo_db[MONGO_CHAT_HISTORY_COLLECTION_NAME]
    centers_collection = mongo_db[MONGO_CENTERS_COLLECTION_NAME]
    alimentacion_collection = mongo_db[MONGO_ALIMENTACION_COLLECTION_NAME]
    clima_collection = mongo_db[MONGO_CLIMA_COLLECTION_NAME]
    logger.info(f"Conexión a MongoDB exitosa. Base de datos: {MONGO_DB_NAME}, Colección de informes: {MONGO_COLLECTION_NAME}, Colección de historial de chat: {MONGO_CHAT_HISTORY_COLLECTION_NAME}, Colección de centros: {MONGO_CENTERS_COLLECTION_NAME}, Colección de alimentación: {MONGO_ALIMENTACION_COLLECTION_NAME}")
except Exception as e:
    logger.error(f"Error al conectar con MongoDB: {e}")

class QuestionRequest(BaseModel):
    user_question: str
    center_id: int
    informe_filename: Optional[str] = None # Opcional si la pregunta es sobre un informe específico

# --- ELIMINADO: Detección manual de preguntas simples ---
# Ahora la IA determina automáticamente qué tipo de pregunta es

def needs_alimentacion_context(question: str) -> bool:
    # Palabras clave para decidir si incluir datos de alimentación
    keywords = ["alimentacion", "alimento", "pez", "peces", "jaula", "biomasa", "MOT", "dieta", "feed", "silo", "doser", "peso"]
    q = question.lower()
    return any(k in q for k in keywords)
def needs_clima_context(question: str) -> bool:
    keywords = ["clima", "temperatura", "oxígeno", "presión", "humedad", "radiación", "viento", "atmósfera", "meteorología", "climatología"]
    q = question.lower()
    return any(k in q for k in keywords)


def is_list_alimentacion_centros_question(question: str) -> bool:
    # Detectar preguntas como '¿para qué centros hay datos de alimentación?' o similares
    patterns = [
        r"para que centros hay datos de alimentaci[óo]n",
        r"centros.*alimentaci[óo]n",
        r"alimentaci[óo]n.*centros",
        r"centros.*tienen.*alimentaci[óo]n",
        r"alimentaci[óo]n.*disponible.*centros"
    ]
    q = question.lower()
    return any(re.search(p, q) for p in patterns)

def detect_period_from_question(question: str):
    """
    Detecta un periodo temporal en la pregunta y retorna un filtro de fechas (start, end) o None.
    Soporta: verano, invierno, primavera, otoño, año, mes, semana, hoy, ayer, etc.
    """
    import re
    from datetime import datetime, timedelta
    q = question.lower()
    now = datetime.utcnow()
    year = now.year
    # Mapas de estaciones (hemisferio sur)
    seasons = {
        "verano": (datetime(year, 12, 21), datetime(year+1, 3, 20)),
        "invierno": (datetime(year, 6, 21), datetime(year, 9, 22)),
        "primavera": (datetime(year, 9, 23), datetime(year, 12, 20)),
        "otoño": (datetime(year, 3, 21), datetime(year, 6, 20)),
    }
    for s, (start, end) in seasons.items():
        if s in q:
            # Si estamos fuera de la estación, ajustar año
            if start > end:
                if now.month < 6:
                    start = start.replace(year=year-1)
                else:
                    end = end.replace(year=year+1)
            return start, end
    # Año específico
    m = re.search(r"(20\d{2})", q)
    if m:
        y = int(m.group(1))
        return datetime(y, 1, 1), datetime(y, 12, 31, 23, 59, 59)
    # Mes específico
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    for i, mes in enumerate(meses, 1):
        if mes in q:
            return datetime(year, i, 1), datetime(year, i, calendar.monthrange(year, i)[1], 23, 59, 59)
    # Última semana
    if "ultima semana" in q or "última semana" in q or "la semana pasada" in q:
        return now - timedelta(days=7), now
    # Hoy
    if "hoy" in q:
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    # Ayer
    if "ayer" in q:
        ayer = now - timedelta(days=1)
        return ayer.replace(hour=0, minute=0, second=0, microsecond=0), ayer.replace(hour=23, minute=59, second=59, microsecond=999999)
    return None

def aggregate_alimentacion(alimentacion_collection, center_name, period=None, limit=100):
    """
    Búsqueda flexible: busca todos los registros donde 'Name' contenga el nombre del centro (case-insensitive).
    Si period es (start, end), filtra por ese rango. Si no, usa los últimos N registros.
    Devuelve agregados: promedio, suma, min, max, count para cada campo numérico relevante.
    Además, incluye una muestra de hasta 5 registros representativos (los más recientes).
    """
    if not center_name:
        return {"resumen": "No se especificó centro para la búsqueda de alimentación."}
    regex = re.compile(re.escape(center_name), re.IGNORECASE)
    match = {"Name": {"$regex": regex}}
    if period:
        start, end = period
        match["FechaHora"] = {"$gte": start, "$lte": end}
        pipeline = [
            {"$match": match},
            {"$sort": {"FechaHora": -1}},
            {"$limit": 10000}
        ]
        docs = list(alimentacion_collection.aggregate(pipeline))
    else:
        docs = list(alimentacion_collection.find(match).sort("FechaHora", -1).limit(limit))
    for doc in docs:
        doc.pop("_id", None)
    if not docs:
        return {"resumen": "No hay datos de alimentación para el periodo/centro consultado."}
    numeric_fields = [k for k, v in docs[0].items() if isinstance(v, (int, float))]
    resumen = {}
    for field in numeric_fields:
        values = [d[field] for d in docs if isinstance(d.get(field), (int, float))]
        if not values:
            continue
        resumen[field] = {
            "promedio": sum(values)/len(values),
            "suma": sum(values),
            "min": min(values),
            "max": max(values),
            "count": len(values)
        }
    resumen["total_registros"] = len(docs)
    resumen["ejemplo_registros"] = docs[:5]
    return resumen
def aggregate_clima(clima_collection, codigo_centro, period=None, limit=100):
    """
    Agrega datos climáticos para un centro específico por código y periodo (si se indica).
    Devuelve promedios, min, max, count y una muestra representativa.
    """
    if not codigo_centro:
        return {"resumen": "No se especificó código de centro para la búsqueda de clima."}

    match = {"codigo_centro": codigo_centro}

    if period:
        start, end = period
        match["fecha"] = {"$gte": start, "$lte": end}
        docs = list(clima_collection.find(match).sort("fecha", -1).limit(10000))
    else:
        docs = list(clima_collection.find(match).sort("fecha", -1).limit(limit))

    for doc in docs:
        doc.pop("_id", None)
        doc["fecha"] = str(doc["fecha"])

    if not docs:
        return {"resumen": "No hay datos de clima disponibles para el periodo/centro."}

    datos_climaticos = [d["datos"] for d in docs if "datos" in d]
    numeric_fields = [k for k, v in datos_climaticos[0].items() if isinstance(v, (int, float))]

    resumen = {}
    for field in numeric_fields:
        values = [d[field] for d in datos_climaticos if isinstance(d.get(field), (int, float))]
        if not values:
            continue
        resumen[field] = {
            "promedio": sum(values)/len(values),
            "min": min(values),
            "max": max(values),
            "count": len(values)
        }

    resumen["total_registros"] = len(datos_climaticos)
    resumen["ejemplo_registros"] = datos_climaticos[:5]
    return resumen


# --- DEFINICIÓN DE HERRAMIENTA PARA EL LLM (Function Calling) ---
# Esto debe ir en la parte superior de tu archivo, fuera de cualquier función.
GET_FULL_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_full_report_analysis",
        "description": "Obtiene el contenido técnico detallado (full_analysis) de uno o varios informes ambientales para análisis o comparación. Úsala cuando el usuario pregunte por datos técnicos específicos (ej. pH, redox, materia orgánica, valores de contaminantes), conclusiones o un análisis profundo de un informe. **Para valores de parámetros como pH o Redox, prioriza los datos generales o promedios del informe para gráficos, a menos que se soliciten 'por estación' o 'por punto de muestreo'.** También sirve si el usuario solicita una comparación o tendencia de múltiples informes (ej. 'los últimos 2 informes').",
        "parameters": {
            "type": "object",
            "properties": {
                "center_id": {
                    "type": "integer",
                    "description": "El ID numérico del centro al que pertenece el informe. Se puede inferir del contexto de la sesión."
                },
                "informe_filename": {
                    "type": "string",
                    "description": "El nombre exacto o una referencia parcial del archivo del informe ambiental (ej. 'Anexo 1 Informe Laboratorio Pirquen 23 marzo 2023.pdf', 'el informe de marzo', 'el anexo 1'). Si el usuario no proporciona un nombre específico, la herramienta buscará el informe más reciente para el centro."
                },
                "num_reports": {
                    "type": "integer",
                    "description": "El NÚMERO DE INFORMES MÁS RECIENTES a recuperar SOLO SI el usuario explícitamente solicita una comparación o menciona 'los últimos N informes' (ej., 'los últimos 3'). No asumas un valor si no se menciona un número específico. Por defecto es 1 si no se especifica un número."
                }
            },
            "required": ["center_id"]
        }
    }
}

# --- MODIFICADO: Agregar db: Session = Depends(get_db) ---
@router.post("/analyze-question/")
async def analyze_question(request: QuestionRequest, db: Session = Depends(get_db)):
    try:
        user_question_lower = request.user_question.lower()
        logger.info(f"Pregunta recibida: '{user_question_lower}' para centro ID: {request.center_id}")

        # --- Preparar contexto básico e inicial (se mantiene igual) ---
        center = db.query(Center).filter(Center.id == request.center_id).first()
        center_name = center.name if center else "desconocido"
        
        all_centers = db.query(Center).all()
        all_centers_data = [
            {"id": c.id, "nombre": c.name, "codigo": c.code, "latitud": c.latitude, "longitud": c.longitude}
            for c in all_centers
        ]

        unified_context: Dict[str, Any] = {
            "centro_actual_seleccionado": {"id": request.center_id, "nombre": center_name},
            "todos_los_centros_disponibles": all_centers_data,
        }

        # --- Flujo unificado: Dejar que la IA determine qué tipo de pregunta es y responda apropiadamente ---
        
        # --- NUEVO BLOQUE: FASE 1 - La IA decide si necesita datos pesados (Function Calling) ---
        messages_for_llm_tool_check = [
            {"role": "system", "content": f"""
            Eres un asistente de IA cuya tarea es determinar qué información necesita el usuario para responder a su pregunta.
            Basado en la pregunta del usuario y el contexto operativo (información sobre centros, informes, datos de alimentación), decide si necesitas usar alguna de las funciones disponibles para obtener datos específicos de la base de datos.
            **No respondas a la pregunta directamente en esta fase; solo genera la llamada a la función si es necesaria.** Si la pregunta no requiere datos específicos de las herramientas disponibles, no llames a ninguna función y continúa a la siguiente fase sin añadir información pesada.
            El centro de interés actual es {center_name} (ID: {request.center_id}). Si el usuario menciona un nombre de archivo, prioriza ese para la función get_full_report_analysis.
            """},
            {"role": "user", "content": request.user_question}
        ]

        logger.info("Iniciando primera llamada al LLM para detección de intención (Function Calling)...")
        first_llm_response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages_for_llm_tool_check,
            tools=[GET_FULL_ANALYSIS_TOOL],
            tool_choice="auto"
        )

        tool_calls = first_llm_response.choices[0].message.tool_calls
        
        # --- Ejecución Condicional de la Herramienta (si el LLM la solicitó) ---
        if tool_calls:
            logger.info(f"LLM solicitó {len(tool_calls)} herramienta(s).")
            # *** NOTA: Por ahora, tu código solo procesa la primera herramienta de la lista.
            # *** Si el LLM realmente solicita 2 herramientas (como en tu log),
            # *** deberías iterar sobre `tool_calls` para ejecutar cada una si es necesario.
            # *** Por simplicidad y para resolver el problema actual, seguiremos con `tool_calls[0]`.
            tool_call = tool_calls[0] 
            function_name = tool_call.function.name

            if function_name == "get_full_report_analysis":
                function_args = {}
                try:
                    function_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    logger.error(f"Error decodificando argumentos JSON para {function_name}: {tool_call.function.arguments}")
                    unified_context["error_tool_call"] = f"Error al decodificar argumentos para {function_name}."

                target_center_id = function_args.get("center_id", request.center_id)
                requested_filename = function_args.get("informe_filename") 
                # --- AQUÍ EMPIEZAN LOS CAMBIOS DENTRO DE ESTE BLOQUE `if function_name == ...` ---
                # 1. Obtener el nuevo parámetro 'num_reports' de los argumentos de la función
                num_reports = function_args.get("num_reports", 1) # Por defecto es 1 si no se especifica

                found_reports_data = [] # Esta lista almacenará todos los informes encontrados

                if target_center_id:
                    query_filter = {"center_id": target_center_id}
                    sort_criteria = [("report_date", -1)] 

                    # 2. Lógica para buscar uno o múltiples informes (REEMPLAZA el bloque 'if requested_filename: ... else: ...' anterior)
                    if requested_filename:
                        logger.info(f"Buscando informe(s) para centro {target_center_id} con referencia: '{requested_filename}'.")
                        regex_pattern = re.compile(re.escape(requested_filename), re.IGNORECASE)
                        query_filter["original_filename"] = {"$regex": regex_pattern}
                        
                        # Usa find() y limit para buscar por nombre de archivo específico o patrón
                        reports_cursor = analyzed_reports_collection.find(
                            query_filter,
                            {"full_analysis": 1, "report_date": 1, "original_filename": 1, "_id": 0} # Proyecta campos adicionales
                        ).sort(sort_criteria).limit(num_reports) 
                        
                        found_reports_data = list(reports_cursor)
                    else:
                        logger.info(f"No se especificó nombre de informe. Buscando los últimos {num_reports} informes para el centro {target_center_id}.")
                        
                        # Usa find() y limit para los N informes más recientes para el centro
                        reports_cursor = analyzed_reports_collection.find(
                            query_filter, 
                            {"full_analysis": 1, "report_date": 1, "original_filename": 1, "_id": 0} # Proyecta campos adicionales
                        ).sort(sort_criteria).limit(num_reports) 
                        
                        found_reports_data = list(reports_cursor)

                # 3. Cómo se agrega el resultado al unified_context (REEMPLAZA el bloque 'if full_analysis_doc: ... else: ...' anterior)
                if found_reports_data:
                    # ¡IMPORTANTE! Cambia la clave a plural y almacena una LISTA de informes
                    unified_context["informes_ambientales_detallados"] = [] 
                    for doc in found_reports_data:
                        if "full_analysis" in doc:
                            unified_context["informes_ambientales_detallados"].append({
                                "filename": doc.get("original_filename"),
                                "report_date": doc.get("report_date"),
                                "analysis": doc["full_analysis"]
                            })
                    logger.info(f"'{len(found_reports_data)}' informe(s) detallado(s) cargado(s) con éxito en el contexto unificado.")
                else:
                    logger.warning(f"No se encontró el campo 'full_analysis' para la descripción '{requested_filename}' en centro {target_center_id} o no hay informes que coincidan.")
                    # Asegúrate de que este mensaje se alinee con tu nueva forma de búsqueda múltiple/último
                    unified_context["informe_ambiental_detallado"] = f"No disponible el análisis detallado para el informe(s) que solicitaste en este centro. Por favor, sé más específico o consulta los informes disponibles."

            # Puedes añadir aquí otros 'elif function_name == "otra_herramienta":' si tienes más herramientas
            # Por ahora, solo tenemos 'get_full_report_analysis'

        else:
            # Esta parte se mantiene igual, es para cuando el LLM NO usa ninguna herramienta
            logger.info("LLM no solicitó 'full_analysis'. Cargando resúmenes de informes disponibles.")
            query_filter_basic = {"center_id": request.center_id}
            if request.informe_filename: # Esto parece ser un remanente, `request.informe_filename` no debería usarse aquí
                query_filter_basic["original_filename"] = request.informe_filename
            
            projection_summary = {
                "report_type": 1, 
                "original_filename": 1, 
                "extracted_at": 1,
                "report_date": 1,
                "_id": 0 
            }
            resumed_docs = list(analyzed_reports_collection.find(query_filter_basic, projection_summary).limit(5))
            unified_context["informes_resumidos_disponibles"] = resumed_docs
            logger.info("Contexto de informes resumidos cargado.")

        # --- Tu lógica existente para contexto de alimentación (se mantiene igual) ---
        alimentacion_centros = alimentacion_collection.distinct("Name")
        clima_codigos = clima_collection.distinct("codigo_centro")
        clima_centros = []
        for codigo in clima_codigos:
            centro = db.query(Center).filter(Center.code == str(codigo)).first()
            if centro:
                clima_centros.append({
                    "id": centro.id,
                    "nombre": centro.name,
                    "codigo": centro.code
                })

        period = detect_period_from_question(request.user_question)
        alimentacion_summary = None
        if needs_alimentacion_context(request.user_question):
            alimentacion_summary = aggregate_alimentacion(alimentacion_collection, center_name, period=period, limit=100)
        clima_summary = None
        if needs_clima_context(request.user_question):
            codigo_centro = center.code if center else None
            if codigo_centro:
                try:
                    codigo_centro = int(codigo_centro)
                except:
                    codigo_centro = None
            clima_summary = aggregate_clima(clima_collection, codigo_centro, period=period, limit=100)
        
        # Actualizar el contexto unificado con todos los datos recolectados
        unified_context["centros_con_alimentacion"] = alimentacion_centros
        unified_context["centros_con_clima"] = clima_centros

        if alimentacion_summary is not None:
            unified_context["resumen_alimentacion_centro_actual"] = alimentacion_summary
        if clima_summary is not None:
            unified_context["resumen_clima_centro_actual"] = clima_summary
        # Convertir el contexto unificado a string JSON formateado
        context_str = json.dumps(unified_context, indent=2, default=str)
        
        # Definir el prompt principal con el contexto operativo
        prompt_content = f"""
Eres un asistente de inteligencia artificial especializado en análisis ambiental y operacional de centros de cultivo de salmones en Chile. Tu objetivo es interpretar preguntas humanas de forma contextual, identificar la intención de la solicitud, y entregar una respuesta clara, útil y fundamentada basada en los datos disponibles.

**PRIORIDAD: Sé conciso y utiliza solo la información estrictamente necesaria del contexto proporcionado para responder a la pregunta. Evita la verbosidad y la inclusión de detalles no solicitados explícitamente. Apunta a la eficiencia en el uso de tokens.**

### 🧠 CONTEXTO OPERATIVO DISPONIBLE

Tienes acceso a múltiples bases de datos relacionadas a centros de cultivo, cada una con información distinta. No todos los centros están presentes en todas las bases.

- **`todos_los_centros_disponibles` (MySQL)**: Catálogo oficial de centros (ID, nombre, código, latitud, longitud).
- **`centro_actual_seleccionado`**: Información del centro que se está consultando.

- **INFORMES AMBIENTALES (analyzed_reports)**: Estudios técnicos del fondo marino que pueden incluir materia orgánica, algas en sedimentos, pH, redox, profundidad, etc.
    - **`informes_ambientales_detallados`**: **Si está presente**, esta es una **lista de objetos JSON**, donde cada objeto contiene el `filename`, `report_date` y el `analysis` completo de un informe ambiental. **Úsala para responder preguntas detalladas, extraer valores específicos o realizar comparaciones y tendencias entre múltiples informes.**
    - **`informes_resumidos_disponibles`**: Si **`informes_ambientales_detallados` NO está presente** y la pregunta no es específica, este campo contendrá metadatos básicos (tipo, nombre de archivo, fecha de extracción/informe) de informes ambientales disponibles. Úsalo para preguntas generales como "¿qué informes hay?" o listar informes.
    - **`nombres_de_informes_disponibles_para_inferencia`**: **(Siempre presente si hay informes)** Lista de nombres de archivos recientes para el centro actual, para ayudar en la identificación.

- **DATOS DE ALIMENTACIÓN (MongoDB)**:
    - **`resumen_alimentacion_centro_actual`**: **Si está presente**, contiene estadísticas agregadas (promedio, suma, min, max) de datos de alimentación para el centro y periodo solicitado (ej. biomasa, consumo de alimento, temperatura del agua).
    - **`centros_con_alimentacion`**: Lista los nombres de los centros que tienen datos de alimentación.
- **DATOS CLIMÁTICOS (MongoDB)**:
    - **`resumen_clima_centro_actual`**: Estadísticas agregadas de condiciones climáticas (temperatura, presión, viento, humedad, etc.) del centro, resumidas desde la base de datos `clima`. Se generan solo si la pregunta lo requiere.
    - **`centros_con_clima`**: Lista de centros (id, nombre, código) que tienen registros en la base `clima`.

Los centros pueden tener nombres distintos en cada base. Por ello, debes hacer *matching inteligente* entre nombres y coordenadas cuando sea necesario.

---

### 🧭 INSTRUCCIONES DINÁMICAS (RAZONAMIENTO FLEXIBLE)

- **Responde Directamente**: Utiliza el contexto proporcionado para responder de manera clara y directa.
- **Detalle vs. Resumen**: Prioriza la información detallada si `informes_ambientales_detallados` o `resumen_alimentacion_centro_actual` están disponibles. Si no, usa los resúmenes o datos básicos.
- **Gráficos y Comparaciones**:
    - Si el usuario solicita un gráfico o una comparación ("gráfico", "comparación", "tendencia", "evolución", "últimos X informes"), busca los datos relevantes dentro de la **lista `informes_ambientales_detallados`**.
    - Si `informes_ambientales_detallados` contiene **múltiples informes**, extrae las series de datos (ej. pH, redox) de cada informe, utilizando su `report_date` o `filename` para diferenciarlos en el gráfico.
    - Si encuentras los datos adecuados, genera un bloque JSON para visualización. Asegúrate de que los nombres de los campos en el JSON del gráfico (`xAxis`, `series.name`, `series.data`) sean consistentes con lo que tu frontend espera. Para comparaciones, cada serie podría representar un informe diferente o un valor a lo largo del tiempo/informes.

- **Gráficos y Comparaciones**:
    - Si el usuario solicita un gráfico o una comparación ("gráfico", "comparación", "visualizar", "evolución", "hazme un gráfico", "crea un gráfico"), y tienes los datos relevantes en el contexto `informes_ambientales_detallados` o `resumen_alimentacion_centro_actual`:
        - **Tu objetivo principal es generar un bloque JSON con el gráfico solicitado.**
        - **Para gráficos generales de parámetros como pH o Redox (cuando no se especifica 'por estación'):**
            - **Usa los valores representativos o promedios del informe, no los datos detallados por estación.**
            - Si hay un solo informe, el `xAxis` puede ser la fecha del informe o un nombre descriptivo (ej. "Informe [Fecha]"). El `series.data` contendrá ese único valor.
            - Si hay varios informes, usa las fechas de los informes como `xAxis`. La serie de datos (`series.data`) debe contener los valores correspondientes extraídos para cada informe.
        - Si el usuario pide explícitamente datos "por estación" o "por punto de muestreo" (ej. "gráfico de pH por estación"), entonces usa esos datos para el gráfico, con las estaciones como `xAxis`.
        - Siempre genera el JSON del gráfico si los datos son adecuados para ello. Si no hay datos suficientes o el formato no es adecuado, informa al usuario.

Ejemplo de formato JSON para gráfico (adaptado para múltiples informes):
```json
{{
    "chart": {{
    "type": "line",
    "title": "Comparación de pH y Redox - Centro Pirquen",
    "xAxis": ["Informe Marzo 2023", "Informe Julio 2023"], // O las fechas o nombres de archivo para cada informe
    "series": [
     {{ "name": "pH (Informe Marzo)", "data": [7.3, 7.4] }}, // Ajusta las series para diferenciar por informe
     {{ "name": "Redox (Informe Julio)", "data": [170, 175] }}
    ]
 }}
}}
```

4. **CONTEXTO ESPECÍFICO DISPONIBLE**:
```json
{context_str}
```


"""
        # Generar la respuesta de la IA
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": prompt_content},
                {"role": "user", "content": request.user_question}
            ],
            max_tokens=30000
        )

        ai_answer = response.choices[0].message.content

        # Intentar extraer bloque JSON de gráfico si existe
        import re, json as pyjson
        chart_data = None
        chart_match = re.search(r'```json\s*({[\s\S]*?})\s*```', ai_answer)
        if chart_match:
            try:
                chart_json = chart_match.group(1)
                chart_obj = pyjson.loads(chart_json)
                if 'chart' in chart_obj:
                    chart_data = chart_obj['chart']
                # Eliminar el bloque JSON de la respuesta textual
                ai_answer = re.sub(r'```json[\s\S]*?```', '', ai_answer).strip()
            except Exception as e:
                logger.error(f"Error al parsear el bloque de gráfico JSON: {e}")
                chart_data = None

        chat_entry = {
            "user_question": request.user_question,
            "ai_answer": ai_answer,
            "center_id": request.center_id,
            "informe_filename": request.informe_filename,
            "timestamp": datetime.utcnow(),
            "tokens_used": response.usage.total_tokens
        }
        chat_history_collection.insert_one(chat_entry)
        audio_base64 = None
        try:
            audio_response = tts_client.audio.speech.create(
                input=ai_answer,
                model=settings.azure_openai_tts_deployment,
                voice="onyx",
                response_format="mp3"
            )
            audio_bytes = audio_response.content
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as tts_e:
            logger.error(f"Error al sintetizar audio para la respuesta: {tts_e}")
            audio_base64 = None
        # Incluir chart si existe
        result = {"answer": ai_answer, "audio_base64": audio_base64}
        if chart_data:
            result["chart"] = chart_data
        return result
    except Exception as e:
        logger.error(f"Error al analizar la pregunta: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al procesar la pregunta: {str(e)}") 