#!/usr/bin/env python3
"""
Script para inicializar la base de datos con datos de ejemplo
"""

from sqlalchemy.orm import sessionmaker
from app.core.database import engine, SessionLocal
from app.models.models import User, Role, Permission, Project, UserProject, user_roles, role_permissions, Center, InformeCentro # Importar InformeCentro
from app.api.v1.endpoints.auth import get_password_hash

def init_db():
    """Inicializar base de datos con datos de ejemplo"""
    
    # Crear tablas primero
    from app.core.database import create_tables
    create_tables()
    print("✅ Tablas creadas")
    
    # Crear sesión
    db = SessionLocal()
    
    try:
        # Verificar si ya hay datos
        if db.query(User).first():
            print("⚠️  La base de datos ya tiene datos. Forzando reinicialización...")
            # Limpiar datos existentes en orden correcto (respetando FK constraints)
            db.query(UserProject).delete()
            db.query(Project).delete()
            db.query(Center).delete() # Añadir eliminación de centros
            db.query(InformeCentro).delete() # Añadir eliminación de informes de centro
            # Eliminar relaciones muchos a muchos antes de eliminar las entidades principales
            db.execute(user_roles.delete())
            db.execute(role_permissions.delete())
            db.query(Permission).delete()
            db.query(Role).delete()
            db.query(User).delete()
            db.commit()
            print("✅ Datos existentes eliminados")
        
        print("🚀 Inicializando base de datos con datos de ejemplo...")
        
        # Crear permisos con nombres que coinciden con el frontend
        permissions = [
            Permission(name="gestionar_configuracion", description="Gestionar configuración del sistema"),
            Permission(name="crear empresas", description="Crear empresas"),
            Permission(name="ver usuario", description="Ver usuarios"),
            Permission(name="ver roles", description="Ver roles"),
            Permission(name="ver inventario", description="Ver inventario"),
            Permission(name="crear usuarios", description="Crear usuarios"),
            Permission(name="editar usuarios", description="Editar usuarios"),
            Permission(name="eliminar usuarios", description="Eliminar usuarios"),
            Permission(name="crear roles", description="Crear roles"),
            Permission(name="editar roles", description="Editar roles"),
            Permission(name="eliminar roles", description="Eliminar roles"),
            Permission(name="crear permisos", description="Crear permisos"),
            Permission(name="editar permisos", description="Editar permisos"),
            Permission(name="eliminar permisos", description="Eliminar permisos"),
            Permission(name="crear proyectos", description="Crear proyectos"),
            Permission(name="editar proyectos", description="Editar proyectos"),
            Permission(name="eliminar proyectos", description="Eliminar proyectos"),
            Permission(name="asignar usuarios", description="Asignar usuarios a proyectos"),
            Permission(name="ver proyectos", description="Ver proyectos"),
        ]
        
        for permission in permissions:
            db.add(permission)
        db.commit()
        print("✅ Permisos creados")
        
        # Crear roles
        admin_role = Role(
            name="admin",
            description="Administrador del sistema"
        )
        user_role = Role(
            name="user",
            description="Usuario estándar"
        )
        manager_role = Role(
            name="manager",
            description="Gerente de proyecto"
        )
        
        db.add(admin_role)
        db.add(user_role)
        db.add(manager_role)
        db.commit()
        print("✅ Roles creados")
        
        # Asignar permisos a roles
        admin_permissions = db.query(Permission).all()
        user_permissions = db.query(Permission).filter(
            Permission.name.in_([
                "ver proyectos", "crear proyectos", "editar proyectos"
            ])
        ).all()
        manager_permissions = db.query(Permission).filter(
            Permission.name.in_([
                "ver proyectos", "crear proyectos", "editar proyectos", "eliminar proyectos",
                "asignar usuarios", "ver usuario", "ver roles"
            ])
        ).all()
        
        admin_role.permissions = admin_permissions
        user_role.permissions = user_permissions
        manager_role.permissions = manager_permissions
        db.commit()
        print("✅ Permisos asignados a roles")
        
        # Crear usuarios
        admin_user = User(
            username="admin",
            email="admin@wisensor.com",
            password_hash=get_password_hash("admin123")
        )
        user1 = User(
            username="user1",
            email="user1@wisensor.com",
            password_hash=get_password_hash("user123")
        )
        manager1 = User(
            username="manager1",
            email="manager1@wisensor.com",
            password_hash=get_password_hash("manager123")
        )
        
        db.add(admin_user)
        db.add(user1)
        db.add(manager1)
        db.commit()
        print("✅ Usuarios creados")
        
        # Asignar roles a usuarios
        admin_user.roles = [admin_role]
        user1.roles = [user_role]
        manager1.roles = [manager_role]
        db.commit()
        print("✅ Roles asignados a usuarios")
        
        # Crear proyectos
        projects = [
            Project(name="Proyecto A", description="Primer proyecto de ejemplo"),
            Project(name="Proyecto B", description="Segundo proyecto de ejemplo"),
            Project(name="Proyecto C", description="Tercer proyecto de ejemplo"),
        ]
        
        for project in projects:
            db.add(project)
        db.commit()
        print("✅ Proyectos creados")
        
        # Asignar usuarios a proyectos
        user_project_assignments = [
            UserProject(user_id=user1.id, project_id=projects[0].id, role_in_project="Desarrollador"),
            UserProject(user_id=manager1.id, project_id=projects[0].id, role_in_project="Gerente"),
            UserProject(user_id=user1.id, project_id=projects[1].id, role_in_project="Tester"),
            UserProject(user_id=manager1.id, project_id=projects[1].id, role_in_project="Gerente"),
        ]
        
        for assignment in user_project_assignments:
            db.add(assignment)
        db.commit()
        print("✅ Asignaciones usuario-proyecto creadas")
        
        print("\n🎉 Base de datos inicializada exitosamente!")
        print("\n📋 Datos de acceso:")
        print("👤 Admin: username=admin, password=admin123")
        print("👤 User: username=user1, password=user123")
        print("👤 Manager: username=manager1, password=manager123")
        
    except Exception as e:
        print(f"❌ Error al inicializar la base de datos: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_db() 