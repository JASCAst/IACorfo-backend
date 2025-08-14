from fastapi import APIRouter

from app.api.v1.endpoints import auth
from app.api.v1.endpoints import users
from app.api.v1.endpoints import roles
from app.api.v1.endpoints import permissions
from app.api.v1.endpoints import projects
from app.api.v1.endpoints import centers
from app.api.v1.endpoints import informes_centro
from app.api.v1.endpoints import question_analyzer
from app.api.v1.endpoints import pdf_analysis
from app.api.v1.endpoints import speech_to_text # Importar el nuevo router de voz a texto
from app.api.v1.endpoints import pdf_data_extractor # Importar el router de extracción de datos PDF

# Cambia esta línea:
# from app.api.v1.endpoints.question_analizer import chat_router as question_analyzer_router

# Por esta:

from app.api.v1.endpoints.question_analizer.chat_router import router as question_analyzer3_router

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(centers.router, prefix="/centers", tags=["centers"])
api_router.include_router(informes_centro.router, prefix="/informes-centro", tags=["informes-centro"])
"""api_router.include_router(question_analyzer.router, prefix="/question-analyzer", tags=["question-analyzer"])"""
api_router.include_router(pdf_analysis.router, prefix="/pdf-analysis", tags=["pdf-analysis"])
api_router.include_router(speech_to_text.router, prefix="/speech-to-text", tags=["speech-to-text"]) # Incluir el nuevo router
api_router.include_router(pdf_data_extractor.router, prefix="/pdf-data-extractor", tags=["pdf-data-extractor"]) 

# api_router.include_router(
#     question_analyzer_router, 
#     prefix="/question-analyzer", 
#     tags=["Question Analyzer (New)"]
# )

api_router.include_router(
    question_analyzer3_router,
    prefix="/question-analyzer",
    tags=["Question Analyzer (New)"]
)