# Backend FastAPI - Wisensor

Este es el backend equivalente del sistema Wisensor desarrollado en Python con FastAPI, replicando todas las funcionalidades del backend original en Node.js.

## 🚀 Características

- **FastAPI**: Framework moderno y rápido para APIs
- **SQLAlchemy**: ORM para manejo de base de datos
- **MySQL**: Base de datos principal
- **JWT**: Autenticación con tokens
- **bcrypt**: Encriptación de contraseñas
- **Pydantic**: Validación de datos
- **CORS**: Soporte para peticiones cross-origin

## 📁 Estructura del Proyecto

```
backend_fastapi/
├── app/                          # Aplicación principal
│   ├── __init__.py
│   ├── main.py                   # Punto de entrada de la app
│   ├── core/                     # Configuración central
│   │   ├── __init__.py
│   │   ├── config.py             # Configuración y variables
│   │   └── database.py           # Configuración de BD
│   ├── models/                   # Modelos de datos
│   │   ├── __init__.py
│   │   └── models.py             # Modelos SQLAlchemy
│   ├── schemas/                  # Esquemas Pydantic
│   │   ├── __init__.py
│   │   └── schemas.py            # Validación de datos
│   └── api/                      # API endpoints
│       ├── __init__.py
│       ├── deps.py               # Dependencias comunes
│       └── v1/                   # API v1
│           ├── __init__.py
│           ├── api.py             # Router principal v1
│           └── endpoints/         # Endpoints específicos
│               ├── __init__.py
│               ├── auth.py        # Autenticación
│               ├── users.py       # Gestión usuarios
│               ├── roles.py       # Gestión roles
│               ├── permissions.py # Gestión permisos
│               ├── projects.py    # Gestión proyectos
│               └── user_projects.py # Asignaciones
├── scripts/                      # Scripts de utilidad
│   ├── __init__.py
│   └── init_db.py                # Inicialización BD
├── run.py                        # Script de ejecución
├── requirements.txt               # Dependencias
└── README.md                     # Este archivo
```

## 🛠️ Instalación

### 1. Crear entorno virtual
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar base de datos
- Crear base de datos MySQL llamada `wisensor_db`
- Ajustar configuración en `app/core/config.py` o crear archivo `.env`

### 4. Inicializar base de datos
```bash
python scripts/init_db.py
```

### 5. Ejecutar el servidor
```bash
python run.py
```

O usando uvicorn directamente:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 3000
```

## 📡 Endpoints Disponibles

### Autenticación
- `POST /api/auth/login` - Login de usuario
- `GET /api/auth/me` - Información del usuario actual

### Usuarios
- `POST /api/users/` - Crear usuario
- `GET /api/users/` - Listar usuarios
- `GET /api/users/{id}` - Obtener usuario específico
- `PUT /api/users/{id}` - Actualizar usuario
- `DELETE /api/users/{id}` - Eliminar usuario

### Roles
- `POST /api/roles/` - Crear rol
- `GET /api/roles/` - Listar roles
- `GET /api/roles/{id}` - Obtener rol específico
- `PUT /api/roles/{id}` - Actualizar rol
- `DELETE /api/roles/{id}` - Eliminar rol

### Permisos
- `POST /api/permissions/` - Crear permiso
- `GET /api/permissions/` - Listar permisos
- `GET /api/permissions/{id}` - Obtener permiso específico
- `PUT /api/permissions/{id}` - Actualizar permiso
- `DELETE /api/permissions/{id}` - Eliminar permiso

### Proyectos
- `POST /api/projects/` - Crear proyecto
- `GET /api/projects/` - Listar proyectos
- `GET /api/projects/{id}` - Obtener proyecto específico
- `PUT /api/projects/{id}` - Actualizar proyecto
- `DELETE /api/projects/{id}` - Eliminar proyecto

### Asignaciones Usuario-Proyecto
- `POST /api/user-projects/` - Asignar usuario a proyecto
- `GET /api/user-projects/` - Listar asignaciones
- `PUT /api/user-projects/{id}` - Actualizar asignación
- `DELETE /api/user-projects/{id}` - Eliminar asignación

## 🔐 Sistema de Autenticación

### Login
```bash
curl -X POST "http://localhost:3000/api/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email": "admin@wisensor.com", "password": "admin123"}'
```

### Usar token en peticiones
```bash
curl -X GET "http://localhost:3000/api/users" \
     -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

## 📚 Documentación Automática

FastAPI genera automáticamente documentación interactiva:
- **Swagger UI**: http://localhost:3000/docs
- **ReDoc**: http://localhost:3000/redoc

## 🔧 Configuración

### Variables de Entorno
Crear archivo `.env`:
```env
DB_HOST=localhost
DB_USER=root
DB_PASS=tu_password
DB_NAME=wisensor_db
JWT_SECRET=tu_secret_key_super_segura
DEBUG=true
```

### Configuración de Base de Datos
- **Host**: localhost
- **Puerto**: 3306 (MySQL por defecto)
- **Base de datos**: wisensor_db
- **Usuario**: root (configurable)
- **Contraseña**: (configurable)

## 🚀 Ventajas de la Nueva Estructura

### Organización Profesional:
1. **Separación de responsabilidades** - Cada módulo tiene su función específica
2. **Escalabilidad** - Fácil agregar nuevas versiones de API
3. **Mantenibilidad** - Código organizado y fácil de navegar
4. **Reutilización** - Dependencias y utilidades compartidas

### Estructura Modular:
- **Core**: Configuración central y base de datos
- **Models**: Modelos de datos SQLAlchemy
- **Schemas**: Validación de datos Pydantic
- **API**: Endpoints organizados por versión
- **Scripts**: Utilidades y herramientas

## 🧪 Testing

Para probar la API:
1. Iniciar el servidor: `python run.py`
2. Ir a http://localhost:3000/docs
3. Usar la interfaz interactiva para probar endpoints

## 📝 Notas

- El servidor corre en el puerto 3000 por defecto
- CORS está configurado para http://localhost:5173 (frontend)
- Las tablas se crean automáticamente al iniciar
- JWT tokens expiran en 30 minutos por defecto
- La estructura sigue las mejores prácticas de FastAPI 