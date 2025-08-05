from fastapi import APIRouter, UploadFile, File, HTTPException, status, Request, Response
import os
from dotenv import load_dotenv
from openai import AzureOpenAI # Importar AzureOpenAI
import logging
import tempfile
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from io import BytesIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Cargar variables de entorno
load_dotenv()

# Configuración de Azure OpenAI (reutilizando el cliente existente)
from app.core.config import settings

# Cliente de OpenAI específico para transcripción
transcription_client = AzureOpenAI(
    api_version=settings.azure_openai_transcription_api_version or settings.azure_openai_api_version,
    azure_endpoint=settings.azure_openai_transcription_endpoint or settings.azure_openai_endpoint,
    api_key=settings.azure_openai_transcription_api_key or settings.azure_openai_api_key,
    http_client=None
)


# Cliente de OpenAI para TTS
tts_client = AzureOpenAI(
    api_version=settings.azure_openai_tts_api_version,
    azure_endpoint=settings.azure_openai_tts_endpoint,
    api_key=settings.azure_openai_tts_api_key,
    http_client=None
)

class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "es-ES-ElviraNeural"  # Puedes cambiar la voz por defecto
    response_format: str = "mp3"  # mp3, wav, etc.
    model: str = "gpt-4o-mini-tts"
  # Puedes cambiar el modelo si tienes otro deployment

@router.post("/transcribe/")
async def transcribe_audio(audio_file: UploadFile = File(...)):
    """
    Recibe un archivo de audio y lo transcribe a texto usando Azure OpenAI (Whisper).
    """
    try:
        audio_content = await audio_file.read()
        logger.info(f"Received audio file: {audio_file.filename}, size: {len(audio_content)} bytes")

        if not audio_content:
            logger.error("Received an empty audio file.")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio file provided.")

        # Usar tempfile para crear un archivo temporal seguro
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio_file:
            temp_audio_file.write(audio_content)
            file_location = temp_audio_file.name

        logger.info(f"Temporary audio file created at: {file_location}, size: {os.path.getsize(file_location)} bytes")
        
        # Transcribir audio usando Azure OpenAI (Whisper)
        with open(file_location, "rb") as audio_fp:
            transcription = transcription_client.audio.transcriptions.create(
                model=settings.azure_openai_transcription_deployment, # Usar un deployment específico para transcripción
                file=audio_fp
            )
        
        transcribed_text = transcription.text
        logger.info(f"Texto Transcrito por Whisper: {transcribed_text}")

        # Eliminar el archivo temporal
        os.remove(file_location)

        return {"transcribedText": transcribed_text}
    except Exception as e:
        logger.error(f"Error en la transcripción de audio con Whisper: {e}")
        # Asegurar que el archivo temporal se elimine incluso si ocurre un error
        if 'file_location' in locals() and os.path.exists(file_location):
            os.remove(file_location)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al procesar el audio: {str(e)}") 

# --- NUEVO ENDPOINT: SÍNTESIS DE TEXTO A VOZ ---
@router.post("/synthesize/")
async def synthesize_text(request: SynthesizeRequest):
    """
    Recibe un texto y lo convierte a audio usando Azure OpenAI TTS.
    Devuelve el audio como stream (audio/mpeg).
    """
    try:
        logger.info(f"Texto a sintetizar: {request.text[:100]}... (voz: {request.voice}, formato: {request.response_format}, modelo: {request.model})")
        audio_response = tts_client.audio.speech.create(
            input=request.text,
            model=request.model,
            voice=request.voice,
            response_format=request.response_format
        )
        audio_bytes = audio_response.content
        logger.info(f"Audio generado, tamaño: {len(audio_bytes)} bytes")
        return StreamingResponse(BytesIO(audio_bytes), media_type=f"audio/{request.response_format}")
    except Exception as e:
        logger.error(f"Error en la síntesis de texto a voz: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al sintetizar el texto: {str(e)}") 