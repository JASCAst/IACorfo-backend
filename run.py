#!/usr/bin/env python3
"""
Script principal para ejecutar la aplicación FastAPI
"""

import uvicorn
from app.core.config import settings
from dotenv import load_dotenv # Importar load_dotenv

load_dotenv() # Cargar variables de entorno desde .env

if __name__ == "__main__":
    print("🚀 Iniciando servidor FastAPI...")
    print(f"📡 Servidor corriendo en http://{settings.host}:{settings.port}")
    print("📚 Documentación disponible en http://localhost:3000/docs")
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    ) 