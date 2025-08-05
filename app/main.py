from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import create_tables
from app.api.v1.api import api_router

# Crear tablas en la base de datos
create_tables()

# Crear aplicación FastAPI
app = FastAPI(
    title=settings.app_name,
    description="Backend API para el sistema Wisensor",
    version=settings.app_version,
    debug=settings.debug,
    redirect_slashes=False
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir cualquier origen para acceso desde toda la red
    allow_credentials=False,  # Debe ser False cuando allow_origins es "*"
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Incluir rutas de la API
app.include_router(api_router, prefix="/api")

# Ruta de prueba
@app.get("/")
def read_root():
    return {
        "message": "🔥🔥🔥 Servidor backend FastAPI cargado y ejecutándose - PRUEBA DE LOG 🔥🔥🔥",
        "version": settings.app_version,
        "docs": "/docs"
    }

# Ruta de salud
@app.get("/health")
def health_check():
    return {"status": "healthy", "message": "Servidor funcionando correctamente"}

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando servidor FastAPI...")
    print(f"📡 Servidor corriendo en http://{settings.host}:{settings.port}")
    print("📚 Documentación disponible en http://localhost:3000/docs")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )