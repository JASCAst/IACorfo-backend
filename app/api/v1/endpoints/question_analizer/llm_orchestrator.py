import json
import logging
from typing import Optional
from openai import AzureOpenAI
from openai import AsyncAzureOpenAI
from app.core.config import settings
from datetime import datetime, timedelta
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = AsyncAzureOpenAI(
        api_version=settings.azure_openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
    )

PLANNER_SYSTEM_PROMPT = """
Eres un planificador experto en acuicultura. Tu tarea es analizar la pregunta del usuario y generar un plan de acción en formato JSON.

Las herramientas disponibles son:
- get_center_id_by_name(center_name: str)
- get_timeseries_data(center_id: int, source: str, metrics: list[str], start_date: Optional[str] = None, end_date: Optional[str] = None, limit: Optional[int] = None)
- get_report_analysis(center_id: int, report_type: Optional[str] = None)
- get_all_centers_info()

--- REGLAS DE ESTRUCTURA (OBLIGATORIO) ---
1. Cada paso en el plan DEBE ser un objeto con TRES claves: `tool`, `parameters`, y `store_result_as`.
2. Los argumentos de la herramienta DEBEN estar dentro del objeto `parameters`.

--- EJEMPLO DE UN PLAN VÁLIDO ---
{
  "plan": [
    {
      "tool": "get_center_id_by_name",
      "parameters": { "center_name": "polocuhe" },
      "store_result_as": "polocuhe_id"
    },
    {
      "tool": "get_timeseries_data",
      "parameters": {
        "source": "clima",
        "metrics": ["temperatura", "viento"],
        "center_id": "${polocuhe_id.center_id}"
      },
      "store_result_as": "clima_polocuhe"
    }
  ]
}
--- FIN DEL EJEMPLO ---

--- REGLAS DE PLANIFICACIÓN ---
1   **CONVERSACIÓN GENERAL:**
    - Si la pregunta es un saludo, una despedida o una pregunta sobre tus capacidades (ej: "¿qué puedes hacer?", "¿qué variables tienes?"), tu única tarea es generar un plan vacío.
    - **Ejemplo de Plan Vacío:** `{"plan": []}`
    
2.  **IDENTIFICACIÓN DEL CENTRO:** Si la pregunta menciona un nombre de centro (ej: "polocuhe"), tu PRIMER paso debe ser llamar a `get_center_id_by_name`. Usa el `center_id` obtenido en los pasos siguientes.

3.  **IDENTIFICACIÓN DE MÉTRICAS Y FUENTES (CLAVE PARA GRÁFICOS):**
    - Analiza qué datos específicos (métricas) pide el usuario.
    - **Métricas de Informes:** "ph", "redox", "materia organica" -> Estos datos provienen EXCLUSIVAMENTE de informes. Usa `get_report_analysis` para obtenerlos. NO uses `get_timeseries_data` para estas métricas.
    
    - **Métricas de Series de Tiempo:**
    - "temperatura", "viento", "presion" -> Usa `source: "clima"` y la lista de `metrics` correspondiente.
    - "tamaño de los peces", "peso de los peces" -> Usa `source: "alimentacion"` y `metrics: ["peso_promedio"]`.
    - "alimentación", "comida", "cantidad de alimento" -> Usa `source: "alimentacion"` y `metrics: ["cantidad_gramos"]`.
    - Si el usuario pide comparar varias métricas de diferentes fuentes (ej: "temperatura y peso de los peces"), DEBES crear un paso `get_timeseries_data` para cada `source`.

4.  **MANEJO DE FECHAS Y LÍMITES:**
    - Si el usuario no especifica un rango de fechas, omite `start_date` y `end_date`. El sistema aplicará un límite por defecto.
    - Si el usuario pide un número específico de datos (ej: "últimos 50"), usa el parámetro `limit`.

5.  **MANEJO DE INFORMES:**
    - Si el usuario menciona un año (ej: "informe del 2023"), un mes (ej: "reporte de marzo") o una fecha, extráela y pásala en el parámetro `date`.
    - "informe ambiental" o "reporte ambiental" -> Usa `get_report_analysis` con `report_type: "informe ambiental"`.
    - "informe comparativo" -> Usa `get_report_analysis` con `report_type: "comparativo"`.
    - **EXCEPCIÓN:** Si el usuario pide comparar métricas (ej: "compara clima y alimentación"), NO llames a `get_report_analysis` a menos que pida explícitamente un "informe".

"""

SYNTHESIZER_SYSTEM_PROMPT = """
Eres un asistente de IA experto en acuicultura. Tu tarea es responder al usuario de forma clara y útil en español, basándote únicamente en el contexto JSON proporcionado.

--- REGLAS DE RESPUESTA (Sigue este orden) ---

1.  **PREGUNTAS GENERALES (CONTEXTO VACÍO):**
    - Si el contexto de datos está vacío, es una pregunta general. Responde amablemente.
    - Si preguntan por tus capacidades (ej: "¿qué puedes hacer?", "¿qué datos tienes?"), DEBES usar este texto: "Soy un asistente de acuicultura. Puedo generar gráficos y darte información sobre las siguientes variables: temperatura, viento, presión, cantidad de alimento, peso promedio de peces, pH y redox. También puedo buscar datos en los informes de los centros. ¿En qué te puedo ayudar?".

2.  **MANEJO DE ERRORES:**
    - Si un resultado en el contexto contiene una clave `"error"`, explica el problema al usuario de forma amigable. No uses la palabra "error".
    - Ejemplo: Si el error es "Centro no encontrado", di "No pude encontrar información para el centro que mencionaste. ¿Podrías verificar el nombre?".

3.  **SÍNTESIS DE DATOS:**
    - Si el contexto tiene datos válidos, sintetiza la información de todas las fuentes para dar una respuesta completa.
    - Al resumir los datos, intenta destacar puntos clave: el valor más alto, el más bajo, el promedio o si una métrica está cerca de un umbral normativo.

--- REGLAS PARA GRÁFICOS (Solo si el usuario pidió un gráfico) ---

A.  **CASO 1 (Series de Tiempo Pre-procesadas):**
    - Si el contexto contiene la clave `"merged_chart_data"`, significa que el gráfico ya está listo. En tu texto, simplemente informa al usuario que el gráfico que pidió está disponible para visualizar.
    - **NO generes ningún bloque JSON en este caso.**

B.  **CASO 2 (Datos de Informes):**
    - Si `merged_chart_data` **NO** está, pero el contexto tiene tablas de un informe:
        1.  **Encuentra la Tabla Correcta:** Busca en el contexto la tabla que contenga las columnas que el usuario pidió (ej: 'ph' y 'redox').
        2.  **Construye el Gráfico:** Genera un bloque de código ```json con la estructura `{"chart": ...}`. El objeto `chart` DEBE contener 4 claves: `type`, `title`, `xAxis`, y `series`.
        3.  **Si no encuentras datos**, informa al usuario que no se encontraron en el informe.
"""

async def create_execution_plan(user_question: str, center_id: Optional[int], contexto_previo: Optional[str] = None) -> dict:
    today = datetime.now().strftime('%Y-%m-%d')
    prompt = f"{PLANNER_SYSTEM_PROMPT}\n\nLa fecha actual es: {today}."

    if contexto_previo:
        prompt += f"\n\nCONVERSACIÓN ANTERIOR (para referencia):\n{contexto_previo}"

    prompt += f"\n\nPregunta del usuario: \"{user_question}\""

    if center_id:
        prompt += f"\nID Canónico del Centro: {center_id}"
    
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "system", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        plan_str = response.choices[0].message.content
        logger.info(f"Plan generado por la IA: {plan_str}")
        return json.loads(plan_str)
    except Exception as e:
        logger.error(f"Error al generar el plan de ejecución: {e}")
        return {"error": "No se pudo generar el plan", "details": str(e)}

async def synthesize_response(user_question: str, context_data: dict) -> str:
    context_str = json.dumps(context_data, indent=2, default=str)
    
    messages = [
        {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Pregunta: \"{user_question}\"\n\nContexto de datos:\n```json\n{context_str}\n```"}
    ]
    
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            temperature=0.2,
            max_tokens=5000
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error al sintetizar la respuesta: {e}")
        return json.dumps({"error": "No se pudo generar la respuesta final", "details": str(e)})
