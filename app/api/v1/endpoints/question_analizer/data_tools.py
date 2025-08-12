import logging
from pymongo import MongoClient
from sqlalchemy.orm import Session
from dateutil import parser as date_parser
from app.core.config import settings
from app.models.models import MasterCenter, Center
from typing import Optional, List, Dict, Any 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEFAULT_TIMESERIES_LIMIT = 100

class ToolExecutor:
    def __init__(self, db_session: Session):
        self.db = db_session
        self.mongo_client = MongoClient(settings.mongo_uri)
        self.mongo_db = self.mongo_client[settings.mongo_db_name]
        self.alimentacion_coll = self.mongo_db["alimentacion"]
        self.clima_coll = self.mongo_db["clima"]
        self.reportes_coll = self.mongo_db["analyzed_reports"]

    def _get_master_center_aliases(self, center_id: int):
        center = self.db.query(MasterCenter).filter(MasterCenter.id == center_id).first()
        return center.aliases if center else None
    
    def _get_all_centers(db: Session):
        centers = db.query(MasterCenter).all()
        return centers

    # --- FUNCIÓN REESCRITA PARA SER MÁS INTELIGENTE ---
    # data_tools.py

    def get_report_analysis(self, center_id: int, report_type: Optional[str] = None, date: Optional[str] = None) -> dict:
        
        # Función "detective" que explora el JSON en busca de tablas.
        def find_all_tables_recursively(data, found_tables):
            if isinstance(data, dict):
                for key, value in data.items():
                    # Consideramos una "tabla" a cualquier lista que contenga al menos 2 diccionarios
                    if isinstance(value, list) and len(value) >= 2 and all(isinstance(i, dict) for i in value):
                        if key not in found_tables: # Evita sobreescribir con tablas anidadas del mismo nombre
                            logger.info(f"Tabla de datos descubierta: '{key}' con {len(value)} registros.")
                            found_tables[key] = value
                    
                    # Sigue buscando recursivamente
                    find_all_tables_recursively(value, found_tables)
            
            elif isinstance(data, list):
                for item in data:
                    find_all_tables_recursively(item, found_tables)

        # --- Lógica principal ---
        logger.info(f"Buscando informe para centro ID {center_id}, tipo: '{report_type or 'cualquiera'}', fecha: '{date or 'más reciente'}'")
        
        mongo_filter = {"center_id": center_id}
        # ... (tu lógica de filtrado por report_type y date) ...
        report = self.reportes_coll.find_one(mongo_filter, sort=[("extracted_at", -1)])
        
        if not report:
            return {"summary": "No se encontraron informes para los criterios especificados."}

        full_analysis = report.get("full_analysis", {})
        
        # Usamos el detective para encontrar todas las tablas en el informe
        discovered_tables = {}
        find_all_tables_recursively(full_analysis, discovered_tables)
        
        # Construimos el resultado final
        informe = full_analysis.get("informe", {}) or full_analysis.get("reporte", {})
        response_data = {
            "filename": report.get("original_filename"),
            "fecha_informe": informe.get("fecha_informe"),
            "comentarios": informe.get("comentarios") or informe.get("conclusiones"),
        }
        
        # Añadimos todas las tablas descubiertas al resultado
        response_data.update(discovered_tables)
        
        return response_data
        
    def get_data_range_summary(self, source: str, center_id: int) -> dict:
        # (Tu código existente)
        logger.info(f"Buscando rango de fechas para fuente '{source}' y centro ID {center_id}")
        aliases = self._get_master_center_aliases(center_id)
        if not aliases: return {"error": "Centro no encontrado."}
        match_filter = {}
        collection = None
        date_field = None
        if source == "alimentacion":
            collection = self.alimentacion_coll
            date_field = "FechaHora"
            alias_key = "alimentacion_db_name"
            if aliases.get(alias_key): match_filter["Name"] = aliases[alias_key]
        elif source == "clima":
            collection = self.clima_coll
            date_field = "fecha"
            alias_key = "clima_db_code"
            if aliases.get(alias_key): match_filter["codigo_centro"] = aliases[alias_key]
        else: return {"error": "Fuente desconocida."}
        if not match_filter: return {"error": "Alias no encontrado para el centro."}
        try:
            first_record = collection.find_one(match_filter, sort=[(date_field, 1)])
            last_record = collection.find_one(match_filter, sort=[(date_field, -1)])
            if not first_record or not last_record: return {"has_data": False}
            return {
                "has_data": True,
                "first_record_date": first_record[date_field].strftime('%Y-%m-%d'),
                "last_record_date": last_record[date_field].strftime('%Y-%m-%d')
            }
        except Exception as e:
            logger.error(f"Error buscando rango de fechas: {e}")
            return {"error": "Error en la base de datos."}

    def get_all_centers_info(self) -> dict:
        # (Tu código existente)
        logger.info("Ejecutando get_all_centers_info")
        try:
            centers = self.db.query(Center).order_by(Center.name).all()
            if not centers: return {"count": 0, "centers": [], "summary": "No se encontraron centros en la base de datos."}
            centers_list = [{"id": center.id, "name": center.name, "code": center.code} for center in centers]
            return {"count": len(centers_list), "centers": centers_list}
        except Exception as e:
            logger.error(f"Error al obtener todos los centros: {e}")
            return {"error": "Ocurrió un error al consultar la base de datos de centros."}


    def get_timeseries_data(self, center_id: int, source: str, metrics: List[str], start_date: Optional[str] = None, end_date: Optional[str] = None, limit: Optional[int] = None) -> dict:
        # --- Mapeo de métricas y alias (sin cambios) ---
        METRIC_MAP = {
            "clima": { "temperatura": "$datos.temperature", "viento": "$datos.speed", "presionat": "$datos.pressure" },
            "alimentacion": { "cantidad_gramos": "$AmountGrams", "peso_promedio": "$PesoProm", "cantidad_peces": "$FishCount" }
        }
        aliases = self._get_master_center_aliases(center_id)
        if not aliases: return {"error": f"Centro con ID maestro {center_id} no encontrado."}
        
        match_filter = {}
        collection = None
        date_field = None

        if source == "alimentacion":
            collection = self.alimentacion_coll
            date_field = "FechaHora"
            if "Name" in aliases: match_filter["Name"] = aliases["Name"]
        elif source == "clima":
            collection = self.clima_coll
            date_field = "fecha"
            if "clima_db_code" in aliases: match_filter["codigo_centro"] = aliases["clima_db_code"]
        else:
            return {"error": f"Fuente de datos '{source}' no reconocida."}

        # --- INICIO DE LA NUEVA LÓGICA DE LÍMITE INTELIGENTE ---
        apply_limit = limit  # Empezamos con el límite que el usuario podría haber especificado

        limit_was_applied_by_default = False
        
        if apply_limit is None:
            apply_limit = DEFAULT_TIMESERIES_LIMIT
        # Caso 1: Petición ambigua sin fechas ni límite explícito.
        if not start_date and not end_date and not limit:
            apply_limit = DEFAULT_TIMESERIES_LIMIT
            limit_was_applied_by_default = True
            logger.info(f"Petición ambigua. Aplicando límite por defecto de los últimos {apply_limit} registros.")

        # Caso 2: Petición para un solo día, sin límite explícito.
        elif start_date and end_date and start_date == end_date and not limit:
            apply_limit = DEFAULT_TIMESERIES_LIMIT
            limit_was_applied_by_default = True
            logger.info(f"Petición para un solo día. Aplicando límite por defecto de {apply_limit} registros.")
        
        # En cualquier otro caso (rango de fechas o límite explícito), apply_limit ya tiene el valor correcto (el del usuario o None).
        # --- FIN DE LA NUEVA LÓGICA ---

        if start_date and end_date:
            match_filter[date_field] = {"$gte": date_parser.parse(start_date), "$lte": date_parser.parse(end_date).replace(hour=23, minute=59, second=59)}

        logger.info(f"Ejecuting query en '{source}' con filtro: {match_filter}")
        pipeline = [{"$match": match_filter}]

        if apply_limit:
            pipeline.append({"$sort": {date_field: -1}})
            pipeline.append({"$limit": apply_limit})

        # --- Proyección y ejecución (sin cambios) ---
        projection = {"_id": 0, "fecha": f"${date_field}"}
        for metric in metrics:
            if metric in METRIC_MAP.get(source, {}):
                projection[metric] = METRIC_MAP[source][metric]
            else:
                logger.warning(f"Métrica '{metric}' no reconocida para la fuente '{source}'.")
        
        if len(projection) > 2:
            pipeline.append({"$project": projection})
        else:
            return {"error": f"Ninguna de las métricas solicitadas {metrics} es válida para la fuente {source}."}

        result = list(collection.aggregate(pipeline))
        logger.info(f"Resultado de la agregación: {len(result)} documentos.")

        return {
            "count": len(result),
            "limit_applied": limit_was_applied_by_default, 
            "data": result
            } if result else {
                "count": 0, 
                "summary": "No se encontraron datos."
                }    

    def get_center_id_by_name(self, center_name: str) -> dict:
        """Busca el ID de un centro por su nombre canónico."""
        logger.info(f"Buscando ID para el centro: '{center_name}'")
        try:
            center = self.db.query(MasterCenter).filter(
                MasterCenter.canonical_name.ilike(f'%{center_name.lower()}%')
            ).first()

            if center:
                # --- INICIO DE LA CORRECCIÓN ---
                # Usamos 'canonical_name' en lugar de 'name'
                logger.info(f"Centro encontrado: {center.canonical_name} con ID: {center.id}")
                return {"center_id": center.id, "center_name": center.canonical_name}
                # --- FIN DE LA CORRECCIÓN ---
            else:
                logger.warning(f"No se encontró ningún centro que coincida con '{center_name}'")
                return {"error": f"No se encontró un centro con el nombre '{center_name}'."}
                
        except Exception as e:
            logger.error(f"Error buscando centro por nombre: {e}")
            return {"error": "Error en la base de datos al buscar el centro."}

