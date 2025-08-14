# app/chat/models.py

from pydantic import BaseModel
from typing import Optional, Any, Dict, List, Union

class QuestionRequest(BaseModel):
    """Define la estructura de la pregunta que llega a la API."""
    user_question: str
    # El center_id aquí es el ID de la tabla maestra `master_centers`
    center_id: Optional[int] = None
    contexto_previo: List[Dict[str, Any]] = []

class ChartData(BaseModel):
    """Define la estructura de un objeto de gráfico para el frontend."""
    type: str
    title: str
    xAxis: List[str]
    series: List[Dict[str, Any]]

class FinalResponse(BaseModel):
    """Define la estructura de la respuesta final de la API."""
    answer: str
    chart: Optional[ChartData] = None
    audio_base64: Optional[str] = None
    debug_context: Optional[Dict[str, Any]] = None # Para depuración
    