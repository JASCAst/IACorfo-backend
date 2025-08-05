from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.models import Center
from app.schemas.schemas import CenterCreate, CenterUpdate, CenterResponse

router = APIRouter()

@router.post("/", response_model=CenterResponse, status_code=status.HTTP_201_CREATED)
def create_center(center: CenterCreate, db: Session = Depends(get_db)):
    db_center = Center(**center.dict())
    db.add(db_center)
    db.commit()
    db.refresh(db_center)
    return db_center

@router.get("/", response_model=List[CenterResponse])
def read_centers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    centers = db.query(Center).offset(skip).limit(limit).all()
    return centers

@router.get("/{center_id}", response_model=CenterResponse)
def read_center(center_id: int, db: Session = Depends(get_db)):
    center = db.query(Center).filter(Center.id == center_id).first()
    if center is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    return center

@router.put("/{center_id}", response_model=CenterResponse)
def update_center(center_id: int, center: CenterUpdate, db: Session = Depends(get_db)):
    db_center = db.query(Center).filter(Center.id == center_id).first()
    if db_center is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    for key, value in center.dict(exclude_unset=True).items():
        setattr(db_center, key, value)
    db.commit()
    db.refresh(db_center)
    return db_center

@router.delete("/{center_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_center(center_id: int, db: Session = Depends(get_db)):
    db_center = db.query(Center).filter(Center.id == center_id).first()
    if db_center is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    db.delete(db_center)
    db.commit()
    return {"message": "Centro eliminado exitosamente"} 