from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from passlib.context import CryptContext
from app.core.database import get_db
from app.models.models import User, Role
from app.schemas.schemas import (
    UserCreate, UserUpdate, UserResponse, UserWithRolesResponse, UserFrontendResponse
)
from app.api.deps import get_current_active_user, has_permission

router = APIRouter()

# Configuración de encriptación
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """Genera hash de la contraseña"""
    return pwd_context.hash(password)

@router.post("/", response_model=UserResponse)
def create_user(user_data: UserCreate, db: Session = Depends(get_db)):
    """Crear nuevo usuario"""
    # Verificar si el usuario ya existe
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | (User.email == user_data.email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario o email ya existe"
        )
    
    # Crear usuario
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hashed_password
    )
    # Asignar roles si se reciben
    if user_data.roles:
        roles = db.query(Role).filter(Role.name.in_(user_data.roles)).all()
        db_user.roles = roles
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.get("/", response_model=List[UserFrontendResponse])
def get_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("ver usuario"))
):
    """Obtener lista de usuarios con sus roles para el frontend"""
    users = db.query(User).offset(skip).limit(limit).all()
    
    # Transformar los datos para el frontend
    frontend_users = []
    for user in users:
        frontend_user = {
            "id": user.id,
            "name": user.username,  # Usar username como name
            "email": user.email,
            "roles": [{"name": role.name} for role in user.roles],
            "status": "Activo" if user.is_active else "Inactivo"
        }
        frontend_users.append(frontend_user)
    
    return frontend_users

@router.get("/{user_id}", response_model=UserWithRolesResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("ver usuario"))
):
    """Obtener usuario específico con sus roles"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    return user

@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Actualizar usuario"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Actualizar campos
    update_data = user_data.dict(exclude_unset=True)
    if "password" in update_data:
        update_data["password_hash"] = get_password_hash(update_data.pop("password"))
    if "roles" in update_data:
        if update_data["roles"] is not None:
            roles = db.query(Role).filter(Role.name.in_(update_data["roles"])).all() if update_data["roles"] else []
            user.roles = roles
        del update_data["roles"]
    for field, value in update_data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(has_permission("eliminar usuarios"))
):
    """Eliminar usuario"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    db.delete(user)
    db.commit()
    return {"message": "Usuario eliminado"} 