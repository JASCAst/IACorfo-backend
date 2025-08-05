from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.models import Role, User, Permission
from app.schemas.schemas import RoleCreate, RoleUpdate, RoleResponse, RoleWithPermissionsResponse
from app.api.deps import get_current_active_user, has_permission

router = APIRouter()

@router.post("/", response_model=RoleResponse)
def create_role(
    role_data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("crear roles"))
):
    """Crear nuevo rol"""
    existing_role = db.query(Role).filter(Role.name == role_data.name).first()
    if existing_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rol ya existe"
        )
    
    db_role = Role(**role_data.dict())
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

@router.get("/", response_model=List[RoleWithPermissionsResponse])
def get_roles(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("ver roles"))
):
    """Obtener lista de roles con sus permisos"""
    roles = db.query(Role).offset(skip).limit(limit).all()
    return roles

@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("ver roles"))
):
    """Obtener rol específico"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado"
        )
    return role

@router.put("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    role_data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("editar roles"))
):
    """Actualizar rol"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado"
        )
    update_data = role_data.dict(exclude_unset=True)
    if "permissions" in update_data:
        if update_data["permissions"] is not None:
            permissions = db.query(Permission).filter(Permission.name.in_(update_data["permissions"])).all() if update_data["permissions"] else []
            role.permissions = permissions
        del update_data["permissions"]
    for field, value in update_data.items():
        setattr(role, field, value)
    db.commit()
    db.refresh(role)
    return role

@router.delete("/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("eliminar roles"))
):
    """Eliminar rol"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado"
        )
    
    db.delete(role)
    db.commit()
    return {"message": "Rol eliminado"} 