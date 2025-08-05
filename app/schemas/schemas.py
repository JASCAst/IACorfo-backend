from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# Schemas para User
class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str
    roles: Optional[List[str]] = []

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    roles: Optional[List[str]] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Schemas para Role
class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None

class RoleCreate(RoleBase):
    pass

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None

class RoleResponse(RoleBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Schemas para Permission
class PermissionBase(BaseModel):
    name: str
    description: Optional[str] = None

class PermissionCreate(PermissionBase):
    pass

class PermissionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class PermissionResponse(PermissionBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Schemas para Project
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class ProjectResponse(ProjectBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Schemas para UserProject
class UserProjectBase(BaseModel):
    user_id: int
    project_id: int
    role_in_project: Optional[str] = None

class UserProjectCreate(UserProjectBase):
    pass

class UserProjectUpdate(BaseModel):
    role_in_project: Optional[str] = None

class UserProjectResponse(UserProjectBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Schemas para Auth
class LoginRequest(BaseModel):
    email: str
    password: str

class UserLoginResponse(BaseModel):
    id: int
    name: str
    email: str
    roles: List[str]
    permisos: List[str]

class TokenResponse(BaseModel):
    token: str
    refresh_token: str  # Nuevo campo para el refresh token
    user: UserLoginResponse

class UserWithRolesResponse(UserResponse):
    roles: List[RoleResponse] = []

class UserFrontendResponse(BaseModel):
    id: int
    name: str  # Usamos username como name
    email: str
    roles: List[dict] = []  # Lista de roles con solo el nombre
    status: str = "Activo"
    
    class Config:
        from_attributes = True

class RoleWithPermissionsResponse(RoleResponse):
    permissions: List[PermissionResponse] = []
    
    class Config:
        from_attributes = True


# Schemas para InformeCentro
class InformeCentroBase(BaseModel):
    center_id: int
    report_type: str
    file_path: str
    filename: str
    is_analyzed: bool = False

class InformeCentroCreate(InformeCentroBase):
    pass

class InformeCentroUpdate(BaseModel):
    report_type: Optional[str] = None
    file_path: Optional[str] = None
    filename: Optional[str] = None
    is_analyzed: Optional[bool] = None

class InformeCentroResponse(InformeCentroBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_analyzed: bool = False # Nuevo campo para indicar si el informe ha sido analizado

    class Config:
        from_attributes = True


# Schemas para Center
class CenterBase(BaseModel):
    name: str
    latitude: float
    longitude: float
    code: str
    name1: Optional[str] = None
    name2: Optional[str] = None

class CenterCreate(CenterBase):
    pass

class CenterUpdate(BaseModel):
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    code: Optional[str] = None
    name1: Optional[str] = None
    name2: Optional[str] = None

class CenterResponse(CenterBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    informes: List[InformeCentroResponse] = [] # Añadido para incluir informes

    class Config:
        from_attributes = True 