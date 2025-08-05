from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings
from app.core.database import get_db
from app.models.models import User
from app.schemas.schemas import LoginRequest, TokenResponse
from app.api.deps import get_current_active_user

router = APIRouter()

# Configuración de encriptación
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña coincide con el hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Genera hash de la contraseña"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Crea token JWT"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt

# NUEVO: función para refresh token
REFRESH_TOKEN_EXPIRE_DAYS = 7

def create_refresh_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt

def authenticate_user(db: Session, email: str, password: str) -> User:
    """Autentica usuario con email y password"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user

@router.post("/login", response_model=TokenResponse)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Login de usuario"""
    print(f"🔍 Debug: Intento de login para email: {login_data.email}")
    
    user = authenticate_user(db, login_data.email, login_data.password)
    if not user:
        print(f"❌ Debug: Usuario no encontrado o contraseña incorrecta para {login_data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )
    
    print(f"✅ Debug: Usuario autenticado: {user.username}")
    print(f"🔍 Debug: Roles del usuario: {[role.name for role in user.roles]}")
    
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    # Obtener todos los permisos del usuario a través de sus roles
    user_permissions = []
    for role in user.roles:
        for permission in role.permissions:
            if permission.name not in user_permissions:
                user_permissions.append(permission.name)
    
    print(f"🔍 Debug: Permisos del usuario: {user_permissions}")
    
    response_data = {
        "token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "name": user.username,
            "email": user.email,
            "roles": [role.name for role in user.roles],
            "permisos": user_permissions
        }
    }
    
    print(f"✅ Debug: Respuesta de login enviada")
    return response_data

@router.post("/refresh")
def refresh_token_endpoint(refresh_token: str = Body(...)):
    """Recibe un refresh token y devuelve un nuevo access token si es válido."""
    from jose import JWTError
    try:
        payload = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=400, detail="Token inválido para refresh")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="Refresh token inválido")
        # Generar nuevo access token
        access_token = create_access_token(data={"sub": user_id})
        return {"token": access_token}
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token inválido o expirado")

@router.get("/me")
def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """Obtener información del usuario actual"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "is_active": current_user.is_active
    } 