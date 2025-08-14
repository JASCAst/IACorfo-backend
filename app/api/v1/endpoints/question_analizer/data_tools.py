# app/chat/data_tools.py

import json
import logging
from pymongo import MongoClient
from sqlalchemy.orm import Session
from dateutil import parser as date_parser
from app.core.config import settings
from app.models.models import MasterCenter, Center
from typing import Optional, List, Dict, Any
import re
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Definimos el diccionario de métricas una sola vez para reutilizarlo en todas las herramientas.
FULL_METRIC_MAP = {
    "clima": {
        "fecha": "FECHA",
        "center_name_field": "NAME",
        "metrics": {
            "temperatura_minima": "$TEMP_MIN_C", 
            "temperatura_maxima": "$TEMP_MAX_C",
            "temperatura_tarde": "$TEMP_TARDE", 
            "presion": "$PRESION_HPA",
            "humedad": "$HUMEDAD_%", 
            "viento": "$VIENTO_VEL_MS",
            "precipitacion": "$PRECIPITACION_TOTAL_MM"
        }
    },
    "alimentacion": {
        "fecha": "Fecha",
        "center_name_field": "Centro",
        "metrics": {
            "alimento_total": "$Alimentos",
            "sfr": "$SFR en período",
            "fcr_biologico": "$FCR Biológico Acum", 
            "crecimiento_bruto": "$Crecimiento bruto",
            "sgr": "$SGR en período", 
            "mortalidad": "$Mortalidad",#porcentaje
            "biomasa_mortalidad": "$Biomasa Mortalidad Acum", #toneladas
            "temperatura_marina": "$Temperatura Promedio", 
            "peso_promedio": "$Desarrollo del Peso Promedio", #gramos
            "biomasa_total_actual":"$Saldo Final Biomasa", #kilos
            "peces_ingresados": "$Número Ingreso",
        }
    }
}

class ToolExecutor:
    """
    Contiene todas las herramientas disponibles que la IA puede ejecutar para
    obtener datos de las bases de datos.
    """
    def __init__(self, db_session: Session):
        self.db = db_session
        self.mongo_client = MongoClient(settings.mongo_uri)
        self.mongo_db = self.mongo_client[settings.mongo_db_name]
        # Asegúrate que los nombres de las colecciones aquí sean los correctos
        self.collections = {
            "clima": self.mongo_db["climaV2"],
            "alimentacion": self.mongo_db["alimentacionV2"]
        }

    def _get_master_center_by_id(self, center_id: int) -> Optional[MasterCenter]:
        """Función auxiliar para obtener un objeto de centro desde la DB relacional."""
        return self.db.query(MasterCenter).filter(MasterCenter.id == center_id).first()

    def _get_all_centers(db: Session):
        centers = db.query(MasterCenter).all()
        return centers

    def _get_alias_value(self, center: MasterCenter, source: str) -> Optional[Any]:
        """Extrae un valor específico del JSON de aliases de un centro."""
        ALIAS_KEYS_MAP = {
            "clima": "climaV2_db_code",
            "alimentacion": "resumenAlimentacion_db_name"
        }
        
        aliases = center.aliases
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except json.JSONDecodeError:
                logger.error(f"La columna 'aliases' para el centro {center.id} no es un JSON válido.")
                return None
        
        if not isinstance(aliases, dict):
            logger.error(f"Los aliases para el centro {center.id} no son un diccionario.")
            return None
            
        alias_key = ALIAS_KEYS_MAP.get(source)
        if not alias_key:
            logger.error(f"No se definió una llave de alias para la fuente '{source}'.")
            return None
            
        alias_value = aliases.get(alias_key)
        if not alias_value:
            logger.error(f"El centro {center.id} no tiene un alias para la llave '{alias_key}'.")
            return None
            
        return alias_value

    def _build_mongo_filter(self, center_id: int, source: str) -> Optional[Dict[str, Any]]:
        """Construye el filtro de MongoDB usando el valor del alias correcto."""
        master_center = self._get_master_center_by_id(center_id)
        if not master_center:
            logger.error(f"No se encontró el MasterCenter con id {center_id}")
            return None
            
        alias_value = self._get_alias_value(master_center, source)
        if alias_value is None:
            return None
            
        mongo_field = FULL_METRIC_MAP[source]["center_name_field"]
        logger.info(f"Filtro construido para MongoDB: {{'{mongo_field}': '{alias_value}'}}")
        return {mongo_field: alias_value}

    def get_center_id_by_name(self, center_name: str) -> dict:
        """Busca el ID de un centro por su nombre."""
        logger.info(f"Buscando ID para el centro: '{center_name}'")
        try:
            center = self.db.query(MasterCenter).filter(MasterCenter.canonical_name.ilike(f'%{center_name.lower()}%')).first()
            if center:
                return {"center_id": center.id, "center_name": center.canonical_name}
            return {"error": f"No se encontró un centro con el nombre '{center_name}'."}
        except Exception as e:
            logger.error(f"Error buscando centro por nombre: {e}")
            return {"error": "Error en la base de datos al buscar el centro."}

    def get_all_centers(self) -> dict:
        """Obtiene una lista de todos los centros de cultivo disponibles."""
        logger.info("Obteniendo lista de todos los centros.")
        try:
            centers = self.db.query(MasterCenter).order_by(MasterCenter.canonical_name).all()
            if not centers: return {"count": 0, "centers": []}
            center_list = [{"id": center.id, "name": center.canonical_name} for center in centers]
            return {"count": len(center_list), "centers": center_list}
        except Exception as e:
            logger.error(f"Error al obtener todos los centros: {e}")
            return {"error": "No se pudo obtener la lista de centros."}
    # En data_tools.py, dentro de la clase ToolExecutor

    def find_centers_with_data(self, source: str) -> dict:
        """
        Verifica cuáles de todos los centros registrados tienen al menos un documento
        en la colección de MongoDB especificada por la fuente.
        """
        logger.info(f"Buscando centros que tengan datos para la fuente: '{source}'")
        if source not in self.collections:
            return {"error": f"La fuente de datos '{source}' no es válida."}

        # 1. Obtenemos todos los centros posibles desde la base de datos SQL.
        all_centers_result = self.get_all_centers()
        if "error" in all_centers_result or not all_centers_result.get("centers"):
            return {"count": 0, "centers_with_data": []}

        centers_with_data = []
        collection_to_check = self.collections[source]

        # 2. Iteramos sobre cada centro y verificamos si tiene datos en MongoDB.
        for center in all_centers_result["centers"]:
            center_id = center["id"]
            
            # Usamos nuestra función auxiliar para construir el filtro preciso
            match_filter = self._build_mongo_filter(center_id, source)
            
            if match_filter:
                # Hacemos una consulta muy rápida para ver si existe al menos un documento.
                has_data = collection_to_check.find_one(match_filter, {"_id": 1})
                if has_data:
                    centers_with_data.append(center["name"])

        return {
            "count": len(centers_with_data),
            "source_checked": source,
            "centers_with_data": sorted(centers_with_data)
        }    

    def get_data_range_for_source(self, center_id: int, source: str) -> dict:
        """Encuentra la primera y última fecha con registros para una fuente y centro."""
        if source not in FULL_METRIC_MAP: return {"error": f"Fuente '{source}' no reconocida."}
        
        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter: return {"error": f"No se pudo crear un filtro para el centro {center_id}."}
        
        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]
        
        pipeline = [{"$match": match_filter}, {"$group": {"_id": None, "min_date": {"$min": f"${date_field}"}, "max_date": {"$max": f"${date_field}"}}}]
        try:
            result = list(collection.aggregate(pipeline))
            if not result or not result[0].get("min_date"): return {"has_data": False}
            return {"has_data": True, "first_record": result[0]["min_date"].strftime('%Y-%m-%d'), "last_record": result[0]["max_date"].strftime('%Y-%m-%d')}
        except Exception as e:
            logger.error(f"Error buscando rango de datos: {e}")
            return {"error": "No se pudo determinar el rango de fechas."}

    def get_timeseries_data(self, center_id: int, source: str, metrics: List[str], start_date: Optional[str] = None, end_date: Optional[str] = None, limit: Optional[int] = None) -> dict:
        """
        Obtiene una serie de tiempo para una o más métricas de una SOLA fuente.
        Aplica un límite por defecto si no se especifica un rango de fechas o un límite explícito.
        """
        logger.info(f"Ejecutando get_timeseries_data para centro ID {center_id}, fuente '{source}'")

        # --- Lógica para determinar el límite a aplicar ---
        default_limit_applied = False
        apply_limit = limit

        # Si el usuario no pide ni un rango de fechas ni un límite, aplicamos uno por defecto.
        if limit is None and not start_date and not end_date:
            apply_limit = 20  # Límite por defecto para una "vista previa"
            default_limit_applied = True
            logger.info(f"No se especificó rango ni límite. Aplicando límite por defecto de {apply_limit} registros.")

        # --- Construcción del filtro ---
        if source not in FULL_METRIC_MAP:
            return {"error": f"Fuente '{source}' no reconocida."}

        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter:
            return {"error": f"No se pudo crear un filtro para el centro {center_id}."}

        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]

        if start_date and end_date:
            try:
                match_filter[date_field] = {"$gte": date_parser.parse(start_date), "$lte": date_parser.parse(end_date).replace(hour=23, minute=59, second=59)}
            except ValueError:
                return {"error": "Formato de fecha inválido. Use AAAA-MM-DD."}

        # --- Construcción de la proyección de métricas ---
        projection = {"_id": 0, "fecha": f"${date_field}"}
        valid_metrics_found = False
        for metric in metrics:
            if metric in config["metrics"]:
                projection[metric] = config["metrics"][metric]
                valid_metrics_found = True

        if not valid_metrics_found:
            return {"error": f"Ninguna de las métricas {metrics} es válida para la fuente {source}."}

        # --- Construcción y ejecución del Pipeline ---
        pipeline = [
            {"$match": match_filter},
            {"$sort": {date_field: -1}}
        ]

        # Aplicamos el límite solo si es necesario
        if apply_limit:
            pipeline.append({"$limit": apply_limit})

        pipeline.extend([
            {"$project": projection},
            {"$sort": {"fecha": 1}} # Re-ordenar cronológicamente para el frontend/IA
        ])

        try:
            result = list(collection.aggregate(pipeline))
            if not result:
                return {"count": 0, "data": [], "summary": "No se encontraron datos."}

            # Devolvemos el resultado junto con la bandera que indica si se usó el límite por defecto
            return {
                "count": len(result),
                "data": result,
                "default_limit_used": default_limit_applied
            }
        except Exception as e:
            logger.error(f"Error en get_timeseries_data: {e}", exc_info=True)
            return {"error": "Ocurrió un error al consultar la base de datos."}

    def correlate_timeseries_data(self, center_id: int, primary_source: str, primary_metrics: List[str], secondary_source: str, secondary_metrics: List[str], start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100) -> dict:
        """Correlaciona métricas de dos fuentes de datos distintas uniéndolas por día."""
        if primary_source not in FULL_METRIC_MAP or secondary_source not in FULL_METRIC_MAP:
            return {"error": "Una de las fuentes de datos no es válida."}
        
        master_center = self._get_master_center_by_id(center_id)
        if not master_center: return {"error": f"Centro con ID {center_id} no encontrado."}

        primary_filter = self._build_mongo_filter(center_id, primary_source)
        secondary_alias_value = self._get_alias_value(master_center, secondary_source)
        
        if not primary_filter or not secondary_alias_value:
            return {"error": f"No se pudieron obtener los aliases necesarios para la correlación en el centro {center_id}."}

        p_config = FULL_METRIC_MAP[primary_source]
        s_config = FULL_METRIC_MAP[secondary_source]
        primary_collection = self.collections[primary_source]
        
        match_filter = primary_filter
        if start_date and end_date:
            match_filter[p_config["fecha"]] = {"$gte": date_parser.parse(start_date), "$lte": date_parser.parse(end_date).replace(hour=23, minute=59, second=59)}

        initial_project = {"_id": 0, "fecha": f"${p_config['fecha']}", **{metric: p_config["metrics"][metric] for metric in primary_metrics if metric in p_config["metrics"]}}
        secondary_projection = {"_id": 0, **{metric: s_config["metrics"][metric] for metric in secondary_metrics if metric in s_config["metrics"]}}

        lookup_stage = {
            "$lookup": {
                "from": self.collections[secondary_source].name,
                "let": {"primary_date": "$fecha"},
                "pipeline": [
                    {"$match": {
                        s_config["center_name_field"]: secondary_alias_value,
                        "$expr": {"$eq": [{"$dateToString": {"format": "%Y-%m-%d", "date": f"${s_config['fecha']}"}}, {"$dateToString": {"format": "%Y-%m-%d", "date": "$$primary_date"}}]}
                    }},
                    {"$project": secondary_projection}
                ],
                "as": "correlated_data"
            }
        }
        
        final_project = {"_id": 0, "fecha": 1, **{metric: 1 for metric in primary_metrics}, **{metric: 1 for metric in secondary_metrics}}

        pipeline = [
            {"$match": match_filter}, {"$sort": {p_config["fecha"]: -1}}, {"$limit": limit},
            {"$project": initial_project},
            lookup_stage,
            {"$unwind": {"path": "$correlated_data", "preserveNullAndEmptyArrays": True}},
            {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$$ROOT", "$correlated_data"]}}},
            {"$project": final_project}, {"$sort": {"fecha": 1}}
        ]

        try:
            result = list(primary_collection.aggregate(pipeline))
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error en la correlación de datos: {e}", exc_info=True)
            return {"error": "No se pudieron correlacionar los datos."}

    
    """ def get_monthly_aggregation(self, center_id: int, source: str, metrics: List[str], aggregation: str) -> dict:
        
        Calcula una agregación mensual (suma o promedio) para una LISTA de métricas.
       
        logger.info(f"Calculando '{aggregation}' mensual para centro ID {center_id}, métricas: {metrics}")

        MONGO_AGG_OPERATORS = {"sum": "$sum", "avg": "$avg"}
        mongo_operator = MONGO_AGG_OPERATORS.get(aggregation.lower())
        if not mongo_operator:
            return {"error": f"Tipo de agregación no válido: '{aggregation}'. Usar 'sum' o 'avg'."}

        if source not in FULL_METRIC_MAP: return {"error": f"Fuente '{source}' no reconocida."}
        
        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter: return {"error": f"No se pudo crear un filtro para el centro {center_id}."}

        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]

        # --- INICIO DEL CAMBIO CLAVE ---
        # Construir dinámicamente las etapas de $group y $project para múltiples métricas
        group_stage = {
            "_id": {"year": {"$year": f"${date_field}"}, "month": {"$month": f"${date_field}"}}
        }
        project_stage = {
            "_id": 0,
            "periodo": {"$concat": [{"$toString": "$_id.year"}, "-", {"$toString": "$_id.month"}]}
        }

        for metric in metrics:
            if metric in config["metrics"]:
                metric_db_field = config["metrics"][metric].replace('$', '')
                # Añadir cada métrica al group stage
                group_stage[f"val_{metric}"] = {mongo_operator: f"${metric_db_field}"}
                # Añadir cada métrica al project stage para redondear y renombrar
                project_stage[metric] = {"$round": [f"$val_{metric}", 2]}
            else:
                logger.warning(f"Métrica '{metric}' omitida por no ser válida para la fuente '{source}'.")

        if len(project_stage) <= 1: # Si solo tiene "periodo"
            return {"error": f"Ninguna de las métricas solicitadas {metrics} es válida."}
        # --- FIN DEL CAMBIO CLAVE ---

        pipeline = [
            {"$match": match_filter},
            {"$group": group_stage},
            {"$sort": {"_id.year": 1, "_id.month": 1}},
            {"$project": project_stage}
        ]
        try:
            result = list(collection.aggregate(pipeline))
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error en la agregación mensual: {e}")
            return {"error": "Error al calcular la agregación mensual."}  """   
    def get_monthly_aggregation(self, center_id: int, source: str, metrics: List[str], aggregation: str, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: Optional[int] = None) -> dict:
        """
        Calcula una agregación mensual para una LISTA de métricas,
        opcionalmente filtrando por fechas o limitando a los N meses más recientes.
        """
        logger.info(f"Calculando '{aggregation}' mensual para centro ID {center_id}, métricas: {metrics}")

        MONGO_AGG_OPERATORS = {"sum": "$sum", "avg": "$avg"}
        mongo_operator = MONGO_AGG_OPERATORS.get(aggregation.lower())
        if not mongo_operator:
            return {"error": f"Tipo de agregación no válido: '{aggregation}'. Usar 'sum' o 'avg'."}

        if source not in FULL_METRIC_MAP: return {"error": f"Fuente '{source}' no reconocida."}
        
        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter: return {"error": f"No se pudo crear un filtro para el centro {center_id}."}

        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]

        if start_date and end_date:
            match_filter[date_field] = {"$gte": date_parser.parse(start_date), "$lte": date_parser.parse(end_date).replace(hour=23, minute=59, second=59)}

        group_stage = {"_id": {"year": {"$year": f"${date_field}"}, "month": {"$month": f"${date_field}"}}}
        project_stage = {"_id": 0, "periodo": {"$concat": [{"$toString": "$_id.year"}, "-", {"$toString": "$_id.month"}]}}

        for metric in metrics:
            if metric in config["metrics"]:
                metric_db_field = config["metrics"][metric].replace('$', '')
                group_stage[f"val_{metric}"] = {mongo_operator: f"${metric_db_field}"}
                project_stage[metric] = {"$round": [f"$val_{metric}", 2]}
        
        if len(project_stage) <= 1:
            return {"error": f"Ninguna de las métricas solicitadas {metrics} es válida."}

        pipeline = [
            {"$match": match_filter},
            {"$group": group_stage},
            {"$sort": {"_id.year": -1, "_id.month": -1}}, # Ordenar descendente para obtener los más recientes
        ]

        # --- INICIO DE LA LÓGICA AÑADIDA ---
        # Si se proporciona un límite, lo aplicamos aquí.
        if limit:
            pipeline.append({"$limit": limit})
        # --- FIN DE LA LÓGICA AÑADIDA ---

        # Volvemos a ordenar ascendente para que el gráfico se vea bien.
        pipeline.append({"$sort": {"_id.year": 1, "_id.month": 1}})
        pipeline.append({"$project": project_stage})

        try:
            result = list(collection.aggregate(pipeline))
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error en la agregación mensual: {e}")
            return {"error": "Error al calcular la agregación mensual."}
            
    def get_extrema_for_metric(self, center_id: int, source: str, metric: str, mode: str = 'max') -> dict:
        """Encuentra el registro con el valor máximo ('max') o mínimo ('min') de una métrica."""
        if source not in FULL_METRIC_MAP or metric not in FULL_METRIC_MAP[source]["metrics"]:
            return {"error": "Fuente o métrica no válida."}
        
        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter: return {"error": f"No se pudo crear un filtro para el centro {center_id}."}
        
        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        metric_db_field = config["metrics"][metric].replace('$', '')
        sort_order = -1 if mode == 'max' else 1

        pipeline = [{"$match": match_filter}, {"$sort": {metric_db_field: sort_order}}, {"$limit": 1}]
        try:
            result = list(collection.aggregate(pipeline))
            if result and '_id' in result[0]: result[0]['_id'] = str(result[0]['_id'])
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error buscando extremo: {e}")
            return {"error": "Error al buscar el valor extremo."}
    def get_monthly_summary_for_all_centers(self, source: str, metric_to_sum: str) -> dict:
        """
        Calcula la suma mensual de una métrica para TODOS los centros de cultivo a la vez.
        """
        logger.info(f"Calculando resumen mensual para todos los centros, métrica: {metric_to_sum}")

        if source not in FULL_METRIC_MAP: 
            return {"error": f"Fuente '{source}' no reconocida."}
            
        config = FULL_METRIC_MAP[source]
        if metric_to_sum not in config["metrics"]: 
            return {"error": f"Métrica '{metric_to_sum}' no válida."}
        
        collection = self.collections[source]
        date_field = config["fecha"]
        center_name_field = config["center_name_field"]
        metric_db_field = config["metrics"][metric_to_sum].replace('$', '')

        pipeline = [
            {
                "$group": {
                    # Agrupamos por dos claves: el centro y el mes/año
                    "_id": {
                        "centro": f"${center_name_field}",
                        "year": {"$year": f"${date_field}"},
                        "month": {"$month": f"${date_field}"}
                    },
                    "total_value": {"$sum": f"${metric_db_field}"}
                }
            },
            {
                # Ordenamos para un resultado más limpio
                "$sort": {
                    "_id.centro": 1, 
                    "_id.year": 1, 
                    "_id.month": 1
                }
            },
            {
                # Proyectamos el resultado en un formato amigable
                "$project": {
                    "_id": 0,
                    "centro": "$_id.centro",
                    "periodo": {"$concat": [{"$toString": "$_id.year"}, "-", {"$toString": "$_id.month"}]},
                    "total": {"$round": ["$total_value", 2]}
                }
            }
        ]
        try:
            result = list(collection.aggregate(pipeline))
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error en la agregación mensual para todos los centros: {e}")
            return {"error": "Error al calcular el resumen mensual para todos los centros."}    
    def get_annual_aggregation(self, center_id: int, source: str, metrics: List[str], aggregation: str, year: int) -> dict:
        """
        Calcula una agregación anual (suma o promedio) para una lista de métricas.
        """
        logger.info(f"Calculando '{aggregation}' anual para centro ID {center_id}, año: {year}")

        MONGO_AGG_OPERATORS = {"sum": "$sum", "avg": "$avg"}
        mongo_operator = MONGO_AGG_OPERATORS.get(aggregation.lower())
        if not mongo_operator:
            return {"error": f"Agregación no válida: '{aggregation}'. Usar 'sum' o 'avg'."}

        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter: return {"error": f"No se pudo crear filtro para el centro {center_id}."}

        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]
        
        # Añadir filtro por año
        start_date = datetime(year, 1, 1)
        end_date = datetime(year + 1, 1, 1)
        match_filter[date_field] = {"$gte": start_date, "$lt": end_date}

        group_stage = {"_id": {"year": {"$year": f"${date_field}"}}}
        project_stage = {"_id": 0, "año": "$_id.year"}

        for metric in metrics:
            if metric in config["metrics"]:
                metric_db_field = config["metrics"][metric].replace('$', '')
                group_stage[f"val_{metric}"] = {mongo_operator: f"${metric_db_field}"}
                project_stage[f"{metric}_{aggregation}"] = {"$round": [f"$val_{metric}", 2]}
            else:
                logger.warning(f"Métrica '{metric}' omitida por no ser válida.")

        if len(project_stage) <= 1:
            return {"error": f"Ninguna de las métricas {metrics} es válida."}

        pipeline = [{"$match": match_filter}, {"$group": group_stage}, {"$project": project_stage}]
        try:
            result = list(collection.aggregate(pipeline))
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error en la agregación anual: {e}")
            return {"error": "Error al calcular la agregación anual."}
    def get_last_reading_for_metric(self, center_id: int, source: str, metric: str) -> dict:
        """Obtiene el registro más reciente basado en la fecha para una métrica."""
        if source not in FULL_METRIC_MAP: return {"error": "Fuente o métrica no válida."}
        
        match_filter = self._build_mongo_filter(center_id, source)
        if not match_filter: return {"error": f"No se pudo crear un filtro para el centro {center_id}."}
        
        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]

        pipeline = [{"$match": match_filter}, {"$sort": {date_field: -1}}, {"$limit": 1}]
        try:
            result = list(collection.aggregate(pipeline))
            if result and '_id' in result[0]: result[0]['_id'] = str(result[0]['_id'])
            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error buscando última lectura: {e}")
            return {"error": "Error al buscar el último registro."}
    # En data_tools.py, dentro de la clase ToolExecutor

    def get_mortality_rate(self, center_ids: Optional[List[int]] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
        """
        Calcula el KPI de mortalidad ponderada, devolviendo el porcentaje y los totales absolutos.
        - Filtra por una lista de centros si se proporciona.
        - Filtra por fecha si se proporciona.
        - Devuelve el estado para todos los centros si no se proporcionan parámetros.
        """
        source = "alimentacion"
        config = FULL_METRIC_MAP[source]
        collection = self.collections[source]
        date_field = config["fecha"]
        center_name_field = config["center_name_field"]

        # 1. Construir el filtro base
        match_filter = {
            # Filtro de calidad: asegurar que el campo del centro exista y no sea nulo
            center_name_field: {"$exists": True, "$ne": None}
        }
        
        # 2. Añadir filtro por centros si se especifica
        if center_ids:
            logger.info(f"Calculando KPI de mortalidad para los centros: {center_ids}")
            alias_values = []
            for center_id in center_ids:
                master_center = self._get_master_center_by_id(center_id)
                if master_center:
                    alias = self._get_alias_value(master_center, source)
                    if alias:
                        alias_values.append(alias)
            
            if not alias_values:
                return {"error": "Ninguno de los IDs de centro proporcionados tiene un alias válido."}
            
            # Añadimos el operador $in al filtro existente
            match_filter[center_name_field]["$in"] = alias_values
        else:
            logger.info("Calculando KPI de mortalidad para todos los centros.")

        # 3. Añadir filtro por fecha si se especifica
        if end_date:
            try:
                # Nos interesa todo lo que sea ANTERIOR O IGUAL a la fecha de fin.
                match_filter[date_field] = {"$lte": date_parser.parse(end_date).replace(hour=23, minute=59, second=59)}
            except ValueError:
                return {"error": "Formato de fecha inválido. Use AAAA-MM-DD."}

        # 4. Pipeline de agregación
        pipeline = [
            {"$match": match_filter},
            {"$sort": {center_name_field: 1, "Unidad": 1, date_field: -1}},
            {"$group": {
                "_id": {"centro": f"${center_name_field}", "unidad": "$Unidad"},
                "last_mortality_percent": {"$first": "$Mortalidad"},
                "initial_stock": {"$first": "$Número Ingreso"}
            }},
            {"$project": {
                "_id": 0, "centro": "$_id.centro", "initial_stock": 1,
                "mortalities_count": {"$multiply": [{"$divide": ["$last_mortality_percent", 100]}, "$initial_stock"]}
            }},
            {"$group": {
                "_id": "$centro",
                "total_mortalities": {"$sum": "$mortalities_count"},
                "total_initial_stock": {"$sum": "$initial_stock"}
            }},
            {"$project": {
                "_id": 0,
                "centro": "$_id",
                "total_peces_ingresados": "$total_initial_stock",
                "total_peces_muertos": {"$round": ["$total_mortalities", 0]},
                "porcentaje_mortalidad_total": {
                    "$cond": {
                        "if": {"$gt": ["$total_initial_stock", 0]},
                        "then": {"$multiply": [{"$divide": ["$total_mortalities", "$total_initial_stock"]}, 100]},
                        "else": 0
                    }
                }
            }},
            {"$sort": {"centro": 1}}
        ]

        try:
            result = list(collection.aggregate(pipeline))
            if not result: return {"count": 0, "data": []}
            
            for item in result:
                item["porcentaje_mortalidad_total"] = round(item["porcentaje_mortalidad_total"], 2)

            return {"count": len(result), "data": result}
        except Exception as e:
            logger.error(f"Error calculando la tasa de mortalidad: {e}")
            return {"error": "Error al calcular la tasa de mortalidad."}
        