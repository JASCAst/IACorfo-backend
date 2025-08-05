from pydantic import BaseModel
from typing import Optional, Any, Dict, List

# --- MOVIDO DESDE TU models.py PRINCIPAL ---
# Estos modelos definen la estructura de datos para la API, no para la base de datos.

class QuestionRequest(BaseModel):
    user_question: str
    # El center_id aquí es el ID de la tabla maestra `master_centers`
    center_id: Optional[int] = None
    contexto_previo: Optional[str] = None

class ChartData(BaseModel):
    type: str
    title: str
    xAxis: List[str]
    series: List[Dict[str, Any]]

class FinalResponse(BaseModel):
    answer: str
    chart: Optional[ChartData] = None
    audio_base64: Optional[str] = None
    debug_context: Optional[Dict[str, Any]] = None # Para depuración
