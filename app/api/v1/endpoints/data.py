from fastapi import APIRouter, Query, HTTPException
from pymongo import MongoClient
from app.core.config import settings
from datetime import datetime, timedelta
from collections import defaultdict


router = APIRouter()

# Configuracion mongo
mongo_db_client = MongoClient(settings.mongo_uri)
wisensor_db = mongo_db_client[settings.mongo_db_name]
alimentacion_col = wisensor_db["alimentacionV2"]
alimentacion_col_original = wisensor_db["alimentacion"]
clima_col = wisensor_db["climaV2"]


# Mapeo entre colecciones
CENTRO_MAP = {
    "Pirquen S23": "Pirquen", #AlimentacionV2,  ClimaV2
    "Polocuhe": "Polocuhe" #AlimentacionV2,  ClimaV2
}

def calculoPromedio(alim_centro: str, clima_centro: str):
    #Alimentacion
    alim_docs = list(alimentacion_col.find({"Centro": alim_centro}))
    if alim_docs:
        fcr_promedio = sum([d.get("FCR Biológico en el periodo", 0) for d in alim_docs]) / len(alim_docs)
        peso_promedio = sum([d.get("Desarrollo del Peso Promedio", 0) for d in alim_docs]) / len(alim_docs)
    else:
        fcr_promedio, peso_promedio = None, None

    #Clima
    clima_docs = list(clima_col.find({"NAME": clima_centro}))
    if clima_docs:
        temp_promedio = sum([(d.get("TEMP_MIN_C", 0) + d.get("TEMP_MAX_C", 0)) / 2 for d in clima_docs]) / len(clima_docs)
        precipitacion_promedio = sum([d.get("PRECIPITACION_TOTAL_MM", 0) for d in clima_docs]) / len(clima_docs)
    else:
        temp_promedio, precipitacion_promedio = None, None

    return {
        "fcr_promedio": round(fcr_promedio, 2) if fcr_promedio else None,
        "peso_promedio": round(peso_promedio, 2) if peso_promedio else None,
        "temperatura_promedio": round(temp_promedio, 2) if temp_promedio else None,
        "precipitacion_promedio": round(precipitacion_promedio, 2) if precipitacion_promedio else None
    }
    
def calculoSemanal(alim_centro: str, clima_centro: str):
    resultados = []
    # Buscar última fecha
    ultimo_doc = alimentacion_col.find_one(
        {"Centro": alim_centro},
        sort=[("Fecha", -1)]
    )

    if not ultimo_doc or not ultimo_doc.get("Fecha"):
        # Si no hay registros, devolver vacío
        resultados[alim_centro] = {
            "consumo_alimentos": {},
            "fcr": {},
            "peso_promedio": {},
            "clima": {}
        }

    fecha_fin = ultimo_doc["Fecha"]
    fecha_inicio = fecha_fin - timedelta(days=6)

    consumo = {}
    fcr = {}
    peso = {}
    clima = {}
    consumoTotal = 0
    fcr_total = 0
    peso_total = 0

    # --- Alimentación ---
    alim_docs = list(alimentacion_col.find({
        "Centro": alim_centro,
        "Fecha": {"$gte": fecha_inicio, "$lte": fecha_fin}
    }))

    for doc in alim_docs:
        fecha_doc = doc.get("Fecha")
        if fecha_doc:
            fecha_str = fecha_doc.strftime("%Y-%m-%d")
            consumo[fecha_str] = doc.get("Alimentos", 0)
            consumoTotal += doc.get("Alimentos", 0)
            consumo["consumoTotal"] = consumoTotal
            
            fcr[fecha_str] = doc.get("FCR Biológico en el periodo", 0)
            fcr_total += doc.get("FCR Biológico en el periodo", 0)
            fcr["fcr_total"] = fcr_total
            
            peso[fecha_str] = doc.get("Desarrollo del Peso Promedio", 0)
            peso_total += doc.get("Desarrollo del Peso Promedio", 0)
            peso["peso_total"] = peso_total

    # --- Clima ---
    clima_docs = list(clima_col.find({
        "NAME": clima_centro, #nombre colunna base de datos
        "FECHA": {"$gte": fecha_inicio, "$lte": fecha_fin} #nombre columna base de datos
    }))

    for doc in clima_docs:
        fecha_doc = doc.get("FECHA")
        if fecha_doc:
            fecha_str = fecha_doc.strftime("%Y-%m-%d")
            temp_prom = (doc.get("TEMP_MIN_C", 0) + doc.get("TEMP_MAX_C", 0)) / 2
            clima[fecha_str] = {
                "temperatura": round(temp_prom, 2),
                "precipitacion": doc.get("PRECIPITACION_TOTAL_MM", 0)
            }
            
    return {
        "consumo_alimentos": consumo,
        "fcr": fcr,
        "peso_promedio": peso,
        "clima": clima
    }

def calculoMensual(alim_centro: str, clima_centro: str):
    alim_docs = list(alimentacion_col.find({"Centro": alim_centro}))
    clima_docs = list(clima_col.find({"NAME": clima_centro}))

    # Si no hay nada, devolvemos estructura vacía
    if not alim_docs and not clima_docs:
        return {
            "consumo_alimentos": [],
            "fcr": [],
            "peso_promedio": [],
            "clima": []
        }

    cons_por_mes = defaultdict(lambda: defaultdict(lambda: {"dias": {}, "total": 0, "count": 0}))
    fcr_por_mes  = defaultdict(lambda: defaultdict(lambda: {"dias": {}, "sum": 0, "count": 0}))
    peso_por_mes = defaultdict(lambda: defaultdict(lambda: {"dias": {}, "sum": 0, "count": 0}))
    clima_por_mes= defaultdict(lambda: defaultdict(lambda: {"dias": {}, "temp_sum": 0, "precip_sum": 0, "count": 0}))

    años_registrados = set()
    
    # Estructuracion de datos 

    # Alimentación
    for doc in alim_docs:
        fecha = doc.get("Fecha")
        if not fecha:
            continue
        y, m = fecha.year, fecha.month
        dkey = fecha.strftime("%Y-%m-%d")
        años_registrados.add(y)

        # Consumo de alimentos
        cons_val = doc.get("Alimentos", 0) or 0
        cons_por_mes[y][m]["dias"][dkey] = cons_val
        cons_por_mes[y][m]["total"] += cons_val
        cons_por_mes[y][m]["count"] += 1

        # FCR
        fcr_val = doc.get("FCR Biológico en el periodo", 0) or 0
        fcr_por_mes[y][m]["dias"][dkey] = fcr_val
        fcr_por_mes[y][m]["sum"] += fcr_val
        fcr_por_mes[y][m]["count"] += 1

        # Peso
        peso_val = doc.get("Desarrollo del Peso Promedio", 0) or 0
        peso_por_mes[y][m]["dias"][dkey] = peso_val
        peso_por_mes[y][m]["sum"] += peso_val
        peso_por_mes[y][m]["count"] += 1

    # Clima
    for doc in clima_docs:
        fecha = doc.get("FECHA")
        if not fecha:
            continue
        y, m = fecha.year, fecha.month
        dkey = fecha.strftime("%Y-%m-%d")
        años_registrados.add(y)

        temp_min = doc.get("TEMP_MIN_C", 0) or 0
        temp_max = doc.get("TEMP_MAX_C", 0) or 0
        temp_prom = (temp_min + temp_max) / 2
        precip = doc.get("PRECIPITACION_TOTAL_MM", 0) or 0

        clima_por_mes[y][m]["dias"][dkey] = {
            "temperatura": round(temp_prom, 2),
            "precipitacion": precip
        }
        clima_por_mes[y][m]["temp_sum"] += temp_prom
        clima_por_mes[y][m]["precip_sum"] += precip
        clima_por_mes[y][m]["count"] += 1

    if not años_registrados:
        return {
            "consumo_alimentos": [],
            "fcr": [],
            "peso_promedio": [],
            "clima": []
        }

    # Determinar rango de años a mostrar
    min_year, max_year = min(años_registrados), max(años_registrados)

    # 
    timeline = []
    for y in range(min_year, max_year + 1):
        for m in range(1, 13):
            timeline.append((y, m))

    def cons_val_mes(y, m):
        data = cons_por_mes[y][m]
        if data["count"] == 0:
            return None
        # Promedio diario mensual:
        return data["total"] / data["count"]

    def fcr_val_mes(y, m):
        data = fcr_por_mes[y][m]
        if data["count"] == 0:
            return None
        return data["sum"] / data["count"]

    def peso_val_mes(y, m):
        data = peso_por_mes[y][m]
        if data["count"] == 0:
            return None
        return data["sum"] / data["count"]

    def clima_vals_mes(y, m):
        data = clima_por_mes[y][m]
        if data["count"] == 0:
            return None, None
        temp_avg = data["temp_sum"] / data["count"]
        precip_total = data["precip_sum"]
        return temp_avg, precip_total

    cons_comp = {}   
    fcr_comp  = {}
    peso_comp = {}
    clima_comp= {}  

    prev_vals = {
        "cons": None,
        "fcr": None,
        "peso": None,
        "clima_temp": None,
        "clima_precip": None
    }

    for (y, m) in timeline:
        # Consumo alimentos comparativa
        curr_cons = cons_val_mes(y, m)
        cons_comp[(y, m)] = (prev_vals["cons"], curr_cons)
        prev_vals["cons"] = curr_cons if curr_cons is not None else prev_vals["cons"]

        # FCR comparativa
        curr_fcr = fcr_val_mes(y, m)
        fcr_comp[(y, m)] = (prev_vals["fcr"], curr_fcr)
        prev_vals["fcr"] = curr_fcr if curr_fcr is not None else prev_vals["fcr"]

        # Peso comparativa
        curr_peso = peso_val_mes(y, m)
        peso_comp[(y, m)] = (prev_vals["peso"], curr_peso)
        prev_vals["peso"] = curr_peso if curr_peso is not None else prev_vals["peso"]

        # Clima comparativa
        curr_temp, curr_precip = clima_vals_mes(y, m)
        clima_comp[(y, m)] = (prev_vals["clima_temp"], curr_temp,
                            prev_vals["clima_precip"], curr_precip)
        prev_vals["clima_temp"] = curr_temp if curr_temp is not None else prev_vals["clima_temp"]
        prev_vals["clima_precip"] = curr_precip if curr_precip is not None else prev_vals["clima_precip"]

    # 
    def estructura_final(raw_dict, tipo: str):

        out = []
        for y in range(min_year, max_year + 1):
            year_block = {"id_año": y, "meses": []}
            for m in range(1, 13):
                month_data = raw_dict[y][m]
                if tipo == "consumo":
                    if month_data["count"] == 0:
                        datos = None
                    else:
                        promedio_diario = round(month_data["total"] / month_data["count"], 2)
                        prev_avg, curr_avg = cons_comp[(y, m)]
                        datos = {
                            "dias": month_data["dias"],  # {"YYYY-MM-DD": valor}
                            "consumoTotalMensual": month_data["total"],
                            # "promedioDiarioMensual": promedio_diario,
                            # "comparativa": {
                            #     "promedio_mes_anterior": round(prev_avg, 2) if prev_avg is not None else None,
                            #     "promedio_mes_actual": round(curr_avg, 2) if curr_avg is not None else None
                            # }
                        }

                elif tipo == "fcr":
                    if month_data["count"] == 0:
                        datos = None
                    else:
                        promedio = round(month_data["sum"] / month_data["count"], 2)
                        prev_avg, curr_avg = fcr_comp[(y, m)]
                        datos = {
                            "dias": month_data["dias"],
                            # "fcrPromedioMensual": promedio,
                            # "comparativa": {
                            #     "promedio_mes_anterior": round(prev_avg, 2) if prev_avg is not None else None,
                            #     "promedio_mes_actual": round(curr_avg, 2) if curr_avg is not None else None
                            # }
                        }

                elif tipo == "peso":
                    if month_data["count"] == 0:
                        datos = None
                    else:
                        promedio = round(month_data["sum"] / month_data["count"], 2)
                        prev_avg, curr_avg = peso_comp[(y, m)]
                        datos = {
                            "dias": month_data["dias"],
                            # "pesoPromedioMensual": promedio,
                            # "comparativa": {
                            #     "promedio_mes_anterior": round(prev_avg, 2) if prev_avg is not None else None,
                            #     "promedio_mes_actual": round(curr_avg, 2) if curr_avg is not None else None
                            # }
                        }

                else:  # clima
                    if month_data["count"] == 0:
                        datos = None
                    else:
                        temp_avg = round(month_data["temp_sum"] / month_data["count"], 2)
                        precip_total = month_data["precip_sum"]
                        p_temp_prev, p_temp_curr, p_prec_prev, p_prec_curr = clima_comp[(y, m)]
                        datos = {
                            "dias": month_data["dias"],  # {"YYYY-MM-DD": {"temperatura": x, "precipitacion": y}}
                            "promedioMensual": {
                                "temperatura": temp_avg,
                                "precipitacionTotal": precip_total
                            },
                            # "comparativa": {
                            #     "temperatura_promedio_mes_anterior": round(p_temp_prev, 2) if p_temp_prev is not None else None,
                            #     "temperatura_promedio_mes_actual": round(p_temp_curr, 2) if p_temp_curr is not None else None,
                            #     "precipitacion_total_mes_anterior": p_prec_prev if p_prec_prev is not None else None,
                            #     "precipitacion_total_mes_actual": p_prec_curr if p_prec_curr is not None else None
                            # }
                        }

                year_block["meses"].append({
                    "id_mes": m,
                    "datos": datos  # <- null si no hay datos
                })
            out.append(year_block)
        return out

    resultado_final = {
        "consumo_alimentos": estructura_final(cons_por_mes, "consumo"),
        "fcr": estructura_final(fcr_por_mes, "fcr"),
        "peso_promedio": estructura_final(peso_por_mes, "peso"),
        "clima": estructura_final(clima_por_mes, "clima")
    }
    return resultado_final


def _parse_fecha(fecha_raw):
    if isinstance(fecha_raw, dict) and "$date" in fecha_raw:
        return datetime.fromisoformat(fecha_raw["$date"].replace("Z", "+00:00"))
    return fecha_raw

def _nuevo_mes_acc():
    
    return {
        "consumo_alimentos": {},
        "fcr": {},      
        "peso_promedio": {},
        "clima": {},
        # Auxiliares para resumen
        "_cons_total": 0,
        "_fcr_sum": 0, "_fcr_cnt": 0,
        "_peso_sum": 0, "_peso_cnt": 0,
        "_temp_sum": 0, "_temp_cnt": 0,
        "_precip_sum": 0,
    }

def _meses_en_orden(m_ini, m_fin):
    res = []
    m = m_ini
    while True:
        res.append(m)
        if m == m_fin:
            break
        m = 1 if m == 12 else m + 1
    return res

def calculoCiclo(alim_centro: str, clima_centro: str):
    # Traer docs ordenados por fecha y parsear fechas
    alim_docs = list(alimentacion_col.find({"Centro": alim_centro}, {
        "Fecha": 1, "Alimentos": 1,
        "FCR Biológico en el periodo": 1,
        "Desarrollo del Peso Promedio": 1
    }).sort("Fecha", 1))

    if not alim_docs:
        return {
            "id_ciclo": None,
            "fecha_inicio": None,
            "fecha_termino": None,
            "meses": []
        }

    for d in alim_docs:
        d["Fecha"] = _parse_fecha(d.get("Fecha"))

    fecha_inicio = alim_docs[0]["Fecha"]
    fecha_termino = alim_docs[-1]["Fecha"]

    # Id ciclo I{YYinicio}F{YYfin}
    id_ciclo = f"I{fecha_inicio.year % 100:02d}F{fecha_termino.year % 100:02d}"

    # acumular por mes (1..12), solo si hay datos
    acc_por_mes = defaultdict(_nuevo_mes_acc)

    # Alimentación
    for doc in alim_docs:
        f = doc["Fecha"]
        mes = f.month
        fkey = f.strftime("%Y-%m-%d")
        cons = doc.get("Alimentos", 0) or 0
        fcr  = doc.get("FCR Biológico en el periodo", 0) or 0
        peso = doc.get("Desarrollo del Peso Promedio", 0) or 0

        mes_acc = acc_por_mes[mes]  
        mes_acc["consumo_alimentos"][fkey] = cons
        mes_acc["fcr"][fkey] = fcr
        mes_acc["peso_promedio"][fkey] = peso

        mes_acc["_cons_total"] += cons
        mes_acc["_fcr_sum"] += fcr
        mes_acc["_fcr_cnt"] += 1
        mes_acc["_peso_sum"] += peso
        mes_acc["_peso_cnt"] += 1

    # Clima (solo dentro del rango del ciclo)
    clima_docs = list(clima_col.find({
        "NAME": clima_centro,
        "FECHA": {"$gte": fecha_inicio, "$lte": fecha_termino}
    }, {
        "FECHA": 1, "TEMP_MIN_C": 1, "TEMP_MAX_C": 1, "PRECIPITACION_TOTAL_MM": 1
    }).sort("FECHA", 1))

    for doc in clima_docs:
        f = _parse_fecha(doc.get("FECHA"))
        if not f:
            continue
        mes = f.month
        fkey = f.strftime("%Y-%m-%d")
        temp_min = doc.get("TEMP_MIN_C", 0) or 0
        temp_max = doc.get("TEMP_MAX_C", 0) or 0
        temp_prom = (temp_min + temp_max) / 2
        precip = doc.get("PRECIPITACION_TOTAL_MM", 0) or 0

        mes_acc = acc_por_mes[mes]
        mes_acc["clima"][fkey] = {
            "temperatura": round(temp_prom, 2),
            "precipitacion": precip
        }
        mes_acc["_temp_sum"] += temp_prom
        mes_acc["_temp_cnt"] += 1
        mes_acc["_precip_sum"] += precip

    meses_presentes = sorted(acc_por_mes.keys())  
    
    orden_ciclo = [m for m in _meses_en_orden(fecha_inicio.month, fecha_termino.month) if m in acc_por_mes]
    
    consumo_total = 0
    fcr_promedio = 0
    peso_promedio = 0
    temperatura_promedio = 0
    precipitacion_total = 0
    
    meses_out = []
    for m in orden_ciclo:
        acc = acc_por_mes[m]

        # Calcular resumen mensual 
        resumen = {
            "consumoTotal": acc["_cons_total"],
            "fcrPromedio": round(acc["_fcr_sum"] / acc["_fcr_cnt"], 2) if acc["_fcr_cnt"] else None,
            "pesoPromedio": round(acc["_peso_sum"] / acc["_peso_cnt"], 2) if acc["_peso_cnt"] else None,
            "temperaturaPromedio": round(acc["_temp_sum"] / acc["_temp_cnt"], 2) if acc["_temp_cnt"] else None,
            "precipitacionTotal": acc["_precip_sum"] if (acc["_temp_cnt"] or acc["_precip_sum"]) else None
        }
        
        consumo_total += resumen["consumoTotal"]
        fcr_promedio += resumen["fcrPromedio"]
        peso_promedio += resumen["pesoPromedio"]
        temperatura_promedio += resumen["temperaturaPromedio"]
        precipitacion_total += resumen["precipitacionTotal"]

        # Armar datos del mes
        datos_mes = {
            "consumo_alimentos": dict(acc["consumo_alimentos"]),
            "fcr": dict(acc["fcr"]),
            "peso_promedio": dict(acc["peso_promedio"]),
            "clima": dict(acc["clima"]),
            "resumen_mensual": resumen
        }

        meses_out.append({
            "idMes": m,
            "datos": datos_mes
        })

    
    return {
        "id_ciclo": id_ciclo,
        "fecha_inicio": fecha_inicio.strftime("%Y-%m-%d"),
        "fecha_termino": fecha_termino.strftime("%Y-%m-%d"),
        "meses": meses_out,
        "resumen_ciclo": {
            "consumoTotal": consumo_total,
            "fcrPromedio": round(fcr_promedio / len(meses_out), 2) if meses_out else None,
            "pesoPromedio": round(peso_promedio / len(meses_out), 2) if meses_out else None,
            "temperaturaPromedio": round(temperatura_promedio / len(meses_out), 2) if meses_out else None,
            "precipitacionTotal": precipitacion_total
        }
    }

@router.get("/dashboard/data")
async def get_series():
    resultados =[]
    for alim_centro, clima_centro in CENTRO_MAP.items():
        semanal = calculoSemanal(alim_centro, clima_centro)
        ciclos = calculoCiclo(alim_centro, clima_centro)
        promedio = calculoPromedio(alim_centro, clima_centro)
        
        resultados.append({
            "nombreCentro": clima_centro,
            "semanales": semanal,
            "ciclos": ciclos,
            "promedios": promedio
        })

    return resultados

