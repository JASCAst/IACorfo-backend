from pydantic import BaseModel
from typing import Optional, Any, Dict, List, Union

# --- MOVIDO DESDE TU models.py PRINCIPAL ---
# Estos modelos definen la estructura de datos para la API, no para la base de datos.

class QuestionRequest(BaseModel):
    user_question: str
    # El center_id aquí es el ID de la tabla maestra `master_centers`
    center_id: Optional[int] = None
    contexto_previo: Union[Dict[str, Any], List[Dict[str, Any]]]

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
