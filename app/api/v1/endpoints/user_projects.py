from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.models import UserProject, User, Project
from app.schemas.schemas import UserProjectCreate, UserProjectUpdate, UserProjectResponse
from app.api.deps import get_current_active_user, has_permission

router = APIRouter()

@router.post("/", response_model=UserProjectResponse)
def create_user_project(
    user_project_data: UserProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("assign_user_project"))
):
    """Asignar usuario a proyecto"""
    # Verificar que usuario y proyecto existen
    user = db.query(User).filter(User.id == user_project_data.user_id).first()
    project = db.query(Project).filter(Project.id == user_project_data.project_id).first()
    
    if not user or not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario o proyecto no encontrado"
        )
    
    # Verificar que no esté ya asignado
    existing_assignment = db.query(UserProject).filter(
        UserProject.user_id == user_project_data.user_id,
        UserProject.project_id == user_project_data.project_id
    ).first()
    
    if existing_assignment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario ya está asignado a este proyecto"
        )
    
    db_user_project = UserProject(**user_project_data.dict())
    db.add(db_user_project)
    db.commit()
    db.refresh(db_user_project)
    return db_user_project

@router.get("/", response_model=List[UserProjectResponse])
def get_user_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Obtener lista de asignaciones usuario-proyecto"""
    user_projects = db.query(UserProject).offset(skip).limit(limit).all()
    return user_projects

@router.put("/{assignment_id}", response_model=UserProjectResponse)
def update_user_project(
    assignment_id: int,
    user_project_data: UserProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("update_user_project"))
):
    """Actualizar asignación usuario-proyecto"""
    user_project = db.query(UserProject).filter(UserProject.id == assignment_id).first()
    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asignación no encontrada"
        )
    
    update_data = user_project_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user_project, field, value)
    
    db.commit()
    db.refresh(user_project)
    return user_project

@router.delete("/{assignment_id}")
def delete_user_project(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("remove_user_project"))
):
    """Eliminar asignación usuario-proyecto"""
    user_project = db.query(UserProject).filter(UserProject.id == assignment_id).first()
    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asignación no encontrada"
        )
    
    db.delete(user_project)
    db.commit()
    return {"message": "Asignación eliminada"} 