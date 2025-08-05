from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import shutil
from pymongo import MongoClient # Importar MongoClient
from app.core.config import settings # Importar settings para MONGO_URI, etc.

from app.core.database import get_db
from app.models.models import InformeCentro, Center
from app.schemas.schemas import InformeCentroCreate, InformeCentroResponse, InformeCentroUpdate, CenterResponse

router = APIRouter()

# Directorio para almacenar los archivos PDF (asegúrate de que exista o créalo)
UPLOAD_DIRECTORY = "uploaded_pdfs"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

# Configurar la conexión a MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://10.20.7.102:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "wisensor_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "analyzed_reports")

mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]
analyzed_reports_collection = mongo_db[MONGO_COLLECTION_NAME]

@router.post("/", response_model=InformeCentroResponse, status_code=status.HTTP_201_CREATED)
async def create_informe_centro(
    center_id: int = Form(...),
    report_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    print(f"Received: center_id={center_id}, report_type={report_type}, filename={file.filename}")
    # Verificar si el centro existe
    center = db.query(Center).filter(Center.id == center_id).first()
    if not center:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Center not found")

    # Contar informes existentes para el centro
    existing_informes_count = db.query(InformeCentro).filter(InformeCentro.center_id == center_id).count()
    if existing_informes_count >= 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 10 reports per center allowed")

    # Guardar el archivo PDF localmente
    file_location = os.path.join(UPLOAD_DIRECTORY, file.filename)
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Crear la entrada en la base de datos
    db_informe = InformeCentro(
        center_id=center_id,
        report_type=report_type,
        file_path=file_location,
        filename=file.filename
    )
    db.add(db_informe)
    db.commit()
    db.refresh(db_informe)
    return db_informe

@router.get("/{informe_id}", response_model=InformeCentroResponse)
def read_informe_centro(informe_id: int, db: Session = Depends(get_db)):
    informe = db.query(InformeCentro).filter(InformeCentro.id == informe_id).first()
    if not informe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="InformeCentro not found")
    return informe

@router.get("/by_center/{center_id}", response_model=List[InformeCentroResponse])
def read_informes_by_center(center_id: int, db: Session = Depends(get_db)):
    informes_db = db.query(InformeCentro).filter(InformeCentro.center_id == center_id).all()
    if not informes_db:
        # No se usa HTTPException 404 porque es posible que un centro no tenga informes aún
        return [] 

    # Convertir a Pydantic Response Model y verificar estado de análisis en MongoDB
    informes_response: List[InformeCentroResponse] = []
    for informe in informes_db:
        # Buscar en MongoDB si este informe ya tiene un análisis
        analyzed_doc = analyzed_reports_collection.find_one({
            "center_id": informe.center_id,
            "original_filename": informe.filename
        })
        
        informe_data = InformeCentroResponse.from_orm(informe).dict()
        informe_data["is_analyzed"] = bool(analyzed_doc) # True si se encontró un documento en MongoDB
        
        informes_response.append(InformeCentroResponse(**informe_data))

    return informes_response

@router.put("/{informe_id}", response_model=InformeCentroResponse)
def update_informe_centro(
    informe_id: int,
    informe_update: InformeCentroUpdate,
    db: Session = Depends(get_db)
):
    db_informe = db.query(InformeCentro).filter(InformeCentro.id == informe_id).first()
    if not db_informe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="InformeCentro not found")
    
    update_data = informe_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_informe, key, value)
    
    db.add(db_informe)
    db.commit()
    db.refresh(db_informe)
    return db_informe

@router.delete("/{informe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_informe_centro(informe_id: int, db: Session = Depends(get_db)):
    db_informe = db.query(InformeCentro).filter(InformeCentro.id == informe_id).first()
    if not db_informe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="InformeCentro not found")
    
    # Eliminar el archivo PDF localmente
    if os.path.exists(db_informe.file_path):
        os.remove(db_informe.file_path)
    
    db.delete(db_informe)
    db.commit()
    return {"detail": "InformeCentro deleted"}
