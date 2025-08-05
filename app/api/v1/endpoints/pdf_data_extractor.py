from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from pypdf import PdfReader
from openai import AzureOpenAI
import os
from dotenv import load_dotenv
from app.core.config import settings
from pymongo import MongoClient
import json
import logging
from datetime import datetime
from typing import Optional # Importar Optional

# Configuración de logging
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
    http_client=None # Añadido para evitar el error de 'proxies'
)

# Configurar la conexión a MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://10.20.7.102:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "wisensor_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "analyzed_reports")

try:
    mongo_client = MongoClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB_NAME]
    analyzed_reports_collection = mongo_db[MONGO_COLLECTION_NAME]
    logger.info(f"Conexión a MongoDB exitosa. Base de datos: {MONGO_DB_NAME}, Colección: {MONGO_COLLECTION_NAME}")
except Exception as e:
    logger.error(f"Error al conectar con MongoDB: {e}")
    # Considerar si esto debe ser un error fatal o permitir que la app siga sin MongoDB

@router.post("/extract-pdf-data/")
async def extract_pdf_data(
    center_id: int = Form(...),
    report_type: str = Form(...),
    file: Optional[UploadFile] = File(None), # Hacer el archivo opcional
    file_path: Optional[str] = Form(None) # Añadir file_path opcional
):
    """
    Sube un archivo PDF o proporciona su ruta, extrae su texto y datos (incluyendo tablas),
    y lo analiza con Azure OpenAI para estructurar la información detallada
    y guardarla en MongoDB.
    """
    if not file and not file_path:
        raise HTTPException(status_code=400, detail="Debe proporcionar un archivo o una ruta de archivo.")

    if file and file_path:
        raise HTTPException(status_code=400, detail="Solo puede proporcionar un archivo o una ruta de archivo, no ambos.")

    pdf_content = None
    original_filename = ""

    if file:
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="El archivo subido debe ser un PDF.")
        pdf_content = file.file
        original_filename = file.filename or ""
    elif file_path:
        full_file_path = os.path.join(os.getenv("UPLOAD_DIRECTORY", "uploaded_pdfs"), os.path.basename(file_path))
        if not os.path.exists(full_file_path):
            raise HTTPException(status_code=404, detail=f"Archivo no encontrado en la ruta: {full_file_path}")
        if not full_file_path.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="La ruta del archivo debe apuntar a un PDF.")
        
        # Leer el archivo directamente del disco
        try:
            pdf_content = open(full_file_path, "rb")
            original_filename = os.path.basename(file_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al leer el archivo desde la ruta: {str(e)}")

    try:
        # 1. Extraer texto del PDF (incluyendo un intento básico de mantener la estructura de tablas)
        pdf_reader = PdfReader(pdf_content)
        text = ""
        for page in pdf_reader.pages:
            # Intentar extraer texto con layout. Esto ayuda a mantener la estructura tabular.
            text += page.extract_text(layout=True) or "" # 'layout=True' es una característica de pypdf

        if not text.strip():
            raise HTTPException(status_code=400, detail="No se pudo extraer texto del PDF o está vacío.")

        # Limitar el texto para evitar exceder el límite de tokens de la API de OpenAI
        # Considerar aumentar este límite si los informes son muy extensos
        MAX_TEXT_LENGTH = 30000  # Caracteres, ajustado para mayor detalle
        original_text_length = len(text)
        if original_text_length > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH] + "\n... [Texto truncado por límite de caracteres. Longitud original: {original_text_length} caracteres]"
            logger.warning(f"Texto del PDF truncado de {original_text_length} a {MAX_TEXT_LENGTH} caracteres.")

        # 2. Enviar el texto a Azure OpenAI para extracción detallada
        # El prompt es CRUCIAL aquí. Debe instruir a la IA a extraer datos estructurados.
        prompt_content = f"""
Eres un asistente experto en analizar documentos técnicos complejos, especialmente informes ambientales, y extraer toda la información relevante de forma estructurada.

Tu tarea es analizar el siguiente informe PDF y extraer todos los datos clave, mediciones, coordenadas, descripciones de eventos, hallazgos, conclusiones y cualquier otra información cuantitativa o cualitativa importante.

Formatea la salida como un objeto JSON. Si hay tablas, intenta representar sus datos dentro del JSON de la manera más estructurada posible (por ejemplo, como una lista de objetos). Si un campo no está presente, omítelo.

Aquí hay ejemplos de información que podrías buscar:
- Fechas de muestreo/informe
- Ubicaciones (nombres, coordenadas geográficas: latitud, longitud)
- Especies (ej. de algas nocivas), sus concentraciones y unidades
- Parámetros ambientales (temperatura, salinidad, pH, oxígeno disuelto), sus valores y unidades
- Descripciones de eventos (ej. floraciones algales, anomalías)
- Metodologías de análisis
- Conclusiones y recomendaciones clave

Asegúrate de que el JSON sea válido y esté bien formado. No incluyas ningún texto adicional fuera del JSON.

Contenido del Informe:
{text}
"""
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": "Eres un asistente diseñado para extraer datos estructurados en formato JSON de documentos técnicos."},
                {"role": "user", "content": prompt_content}
            ],
            response_format={"type": "json_object"} # Indicar a OpenAI que esperamos un JSON
        )

        extracted_json_str = response.choices[0].message.content
        logger.info(f"DEBUG: Tokens utilizados en la solicitud de extracción: {response.usage.total_tokens}")

        # 3. Validar y parsear el JSON
        try:
            extracted_data = json.loads(extracted_json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Error al parsear el JSON de la IA: {e}. Raw AI response: {extracted_json_str}")
            raise HTTPException(status_code=500, detail=f"La IA no devolvió un JSON válido: {str(e)}")

        # 4. Preparar el documento para MongoDB
        # Añadir metadatos del informe y del centro
        mongo_document = {
            "center_id": center_id,
            "report_type": report_type,
            "original_filename": original_filename, # Usar el nombre de archivo determinado
            "extracted_at": datetime.utcnow(), # Usar UTC para consistencia
            "full_analysis": extracted_data, # Aquí irá el JSON extraído por la IA
            "openai_tokens_used": response.usage.total_tokens,
            # Podrías añadir más campos aquí, como la ruta al PDF original si es relevante para el acceso posterior
        }

        # 5. Guardar en MongoDB
        result = analyzed_reports_collection.insert_one(mongo_document)
        logger.info(f"Documento insertado en MongoDB con _id: {result.inserted_id}")

        return {"message": "Análisis y extracción de PDF completados y guardados en MongoDB.", "inserted_id": str(result.inserted_id)}

    except Exception as e:
        logger.error(f"Error general en la extracción de PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar el PDF o interactuar con la IA/MongoDB: {str(e)}")
    finally:
        if file_path and pdf_content:
            pdf_content.close() # Asegurarse de cerrar el archivo si se abrió desde una ruta 