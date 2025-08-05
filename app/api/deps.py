from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from app.core.config import settings
from app.core.database import get_db
from app.models.models import User, Role, Permission

# Configuración de seguridad
security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Obtiene el usuario actual basado en el token JWT"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    print(f"🔍 Debug: Token recibido: {credentials.credentials[:20]}...")
    
    try:
        payload = jwt.decode(
            credentials.credentials, 
            settings.jwt_secret, 
            algorithms=[settings.jwt_algorithm]
        )
        user_id_str = payload.get("sub")
        print(f"🔍 Debug: User ID extraído (string): {user_id_str}")
        if user_id_str is None:
            print("❌ Debug: No se encontró user_id en el token")
            raise credentials_exception
        
        try:
            user_id: int = int(user_id_str)
        except (ValueError, TypeError):
            print(f"❌ Debug: No se pudo convertir {user_id_str} a int")
            raise credentials_exception
            
    except JWTError as e:
        print(f"❌ Debug: Error decodificando JWT: {e}")
        raise credentials_exception
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        print(f"❌ Debug: Usuario con ID {user_id} no encontrado")
        raise credentials_exception
    
    print(f"✅ Debug: Usuario autenticado: {user.username}")
    return user

def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Verifica que el usuario esté activo"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Usuario inactivo")
    return current_user

def get_user_permissions(user: User) -> list:
    """Obtiene todos los permisos del usuario"""
    permissions = []
    for role in user.roles:
        for permission in role.permissions:
            if permission.name not in permissions:
                permissions.append(permission.name)
    return permissions

def get_user_roles(user: User) -> list:
    """Obtiene todos los roles del usuario"""
    return [role.name for role in user.roles]

def has_permission(permission: str):
    """Decorator para verificar si el usuario tiene un permiso específico"""
    def permission_checker(current_user: User = Depends(get_current_active_user)):
        user_permissions = get_user_permissions(current_user)
        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permiso para realizar esta acción"
            )
        return current_user
    return permission_checker

def has_role(role: str):
    """Decorator para verificar si el usuario tiene un rol específico"""
    def role_checker(current_user: User = Depends(get_current_active_user)):
        user_roles = get_user_roles(current_user)
        if role not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene el rol necesario para realizar esta acción"
            )
        return current_user
    return role_checker 