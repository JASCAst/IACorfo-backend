import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Configuración de la aplicación
    app_name: str = "Wisensor API"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Configuración de servidor
    host: str = "0.0.0.0"
    port: int = 3000
    
    # Configuración de base de datos
    db_host: str = "10.20.7.102"
    db_user: str = "fastapi"
    db_pass: str = "Wi$3nS0rIA!"
    db_name: str = "fastapi_db"
    db_port: int = 3306
    
    # Configuración JWT
    jwt_secret: str = "your-super-secret-key-change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440 # Aumentado para desarrollo (24 horas)
    
    # Configuración CORS
    cors_origins: list = ["http://10.20.7.101:5173", "http://10.20.7.102:5173", "https://wisensoria.iotlink.cl","https://apiwisensoria.iotlink.cl"]
    
    # Configuración de seguridad
    bcrypt_rounds: int = 12

    # Configuración de Azure OpenAI
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_model_name: str = "gpt-4.1" # O el nombre del modelo que uses en Azure
    azure_openai_deployment: str = "gpt-4.1-2" # O el nombre de tu deployment en Azure
    azure_openai_api_version: str = "2024-02-15-preview" # Versión de API recomendada por Azure (puedes ajustarla)
    azure_openai_transcription_deployment: str = "gpt-4o-mini-transcribe" # Nombre del deployment de Whisper en Azure OpenAI

    # Configuración específica para el servicio de transcripción (si tiene credenciales separadas)
    azure_openai_transcription_endpoint: Optional[str] = None
    azure_openai_transcription_api_key: Optional[str] = None
    azure_openai_transcription_api_version: Optional[str] = None
    
    # Variables independientes para TTS
    azure_openai_tts_api_key: str = ""
    azure_openai_tts_endpoint: str = ""
    azure_openai_tts_api_version: str = "2024-02-15-preview"
    azure_openai_tts_deployment: str = "tts-1"
    
    azure_openai_embedding_deployment: str = "text-embedding-ada-002"
    # --- AÑADE ESTAS LÍNEAS PARA MONGODB ---
    mongo_uri: str
    mongo_db_name: str = "wisensor_db"

    class Config:
        env_file = ".env"
        case_sensitive = False
        env_file_encoding = "utf-8"

# Instancia global de configuración
settings = Settings()
 