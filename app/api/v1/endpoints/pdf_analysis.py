from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from PyPDF2 import PdfReader # Revertido a PyPDF2
from openai import AzureOpenAI # Cambiado a AzureOpenAI
import os
from app.core.config import settings # Importar la instancia global de settings

router = APIRouter()

# Configurar el cliente de Azure OpenAI
# Usar las configuraciones cargadas desde las settings
# print(f"DEBUG: OpenAI API Key cargada (parcial): {settings.openai_api_key[:5]}...{settings.openai_api_key[-5:]}") # TEMPORAL: Eliminar después de verificar - ELIMINADA
client = AzureOpenAI(
    api_version=settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
)

@router.post("/analyze-pdf/")
async def analyze_pdf(file: UploadFile = File(...)):
    """
    Sube un archivo PDF, extrae su texto y lo analiza con ChatGPT para generar un resumen.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF.")

    try:
        # Leer el contenido del PDF
        pdf_reader = PdfReader(file.file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""

        if not text.strip():
            raise HTTPException(status_code=400, detail="No se pudo extraer texto del PDF o está vacío.")

        # Limitar el texto para evitar exceder el límite de tokens de la API de OpenAI
        # Puedes ajustar este valor según el modelo que uses y tus necesidades.
        # Un token es aproximadamente 4 caracteres para texto en inglés.
        MAX_TEXT_LENGTH = 10000 # Caracteres
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH] + "..." # Truncamos el texto y añadimos elipsis

        # Enviar el texto a ChatGPT para un resumen
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment, # Usar el nombre del deployment de Azure
            messages=[
                {"role": "system", "content": "Eres un asistente experto en analizar documentos técnicos y resumir información clave."},
                {"role": "user", "content": f"Por favor, analiza el siguiente documento técnico y proporciona un resumen conciso de los puntos clave, hallazgos importantes y conclusiones. Asegúrate de destacar cualquier información crucial o datos relevantes:\n\n{text}"}
            ]
        )

        print(f"DEBUG: Tokens utilizados en la solicitud: {response.usage.total_tokens}") # TEMPORAL: Eliminar después de verificar

        summary = response.choices[0].message.content
        # Enriquecer la respuesta con más detalles si es necesario para el frontend
        # Por ahora, simularemos algunos datos para topics y entities
        # Idealmente, estos también serían generados por la IA o extraídos del resumen.
        topics = ["Análisis de datos", "Tecnología IA", "Aplicaciones de sensores"]
        entities = ["Wisensor", "ChatGPT", "FastAPI"]

        return {"filename": file.filename, "summary": summary, "topics": topics, "entities": entities, "full_analysis": summary} # "full_analysis" por ahora es el mismo summary

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el PDF o interactuar con la IA: {str(e)}") 