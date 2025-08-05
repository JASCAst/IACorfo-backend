from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.models import Permission, User
from app.schemas.schemas import PermissionCreate, PermissionUpdate, PermissionResponse
from app.api.deps import get_current_active_user, has_permission

router = APIRouter()

@router.post("/", response_model=PermissionResponse)
def create_permission(
    permission_data: PermissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("crear permisos"))
):
    """Crear nuevo permiso"""
    existing_permission = db.query(Permission).filter(Permission.name == permission_data.name).first()
    if existing_permission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permiso ya existe"
        )
    
    db_permission = Permission(**permission_data.dict())
    db.add(db_permission)
    db.commit()
    db.refresh(db_permission)
    return db_permission

@router.get("/", response_model=List[PermissionResponse])
def get_permissions(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("gestionar_configuracion"))
):
    """Obtener lista de permisos"""
    permissions = db.query(Permission).offset(skip).limit(limit).all()
    return permissions

@router.get("/{permission_id}", response_model=PermissionResponse)
def get_permission(
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("gestionar_configuracion"))
):
    """Obtener permiso específico"""
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permiso no encontrado"
        )
    return permission

@router.put("/{permission_id}", response_model=PermissionResponse)
def update_permission(
    permission_id: int,
    permission_data: PermissionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("editar permisos"))
):
    """Actualizar permiso"""
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permiso no encontrado"
        )
    
    update_data = permission_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(permission, field, value)
    
    db.commit()
    db.refresh(permission)
    return permission

@router.delete("/{permission_id}")
def delete_permission(
    permission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("eliminar permisos"))
):
    """Eliminar permiso"""
    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permiso no encontrado"
        )
    
    db.delete(permission)
    db.commit()
    return {"message": "Permiso eliminado"} 