"""Consultas SQL analíticas para el Hito 2 de MotoExpres BI.
Implementa el motor de cálculo de los seis indicadores oficiales,
análisis multidimensional y control de acceso por región (RLS) en SQL.
"""
from __future__ import annotations

import math
from typing import Any
from app.models.database import consultar, escalar


def _construir_clausula_where(
    perfil: str = "gerencia_general",
    region: str | None = None,
    filtros: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Construye las cláusulas WHERE y los parámetros seguros para SQL.
    Aplica RLS (Row-Level Security) de acuerdo al perfil del usuario.
    """
    condiciones = []
    params: dict[str, Any] = {}

    # Control de Acceso (RLS)
    if perfil == "invitado":
        condiciones.append("1 = 0")  # Acceso denegado: ningún registro
    elif perfil == "gerente_regional":
        if region:
            condiciones.append("c.region = %(region_rls)s")
            params["region_rls"] = region
        else:
            condiciones.append("1 = 0")
    # gerencia_general no añade restricción de región a nivel de RLS

    # Filtros interactivos del usuario
    if filtros:
        anio = filtros.get("anio")
        if anio and str(anio).lower() not in ("todos", "all", ""):
            condiciones.append("t.anio = %(filtro_anio)s")
            params["filtro_anio"] = int(anio)

        mes = filtros.get("mes")
        if mes and str(mes).lower() not in ("todos", "all", ""):
            condiciones.append("t.mes = %(filtro_mes)s")
            params["filtro_mes"] = int(mes)

        servicio_id = filtros.get("servicio_id")
        if servicio_id and str(servicio_id).lower() not in ("todos", "all", ""):
            condiciones.append("f.servicio_id = %(filtro_servicio)s")
            params["filtro_servicio"] = int(servicio_id)

        centro_id = filtros.get("centro_id")
        if centro_id and str(centro_id).lower() not in ("todos", "all", ""):
            condiciones.append("f.centro_id = %(filtro_centro)s")
            params["filtro_centro"] = int(centro_id)

        estado = filtros.get("estado")
        if estado and str(estado).lower() not in ("todos", "all", ""):
            condiciones.append("f.estado = %(filtro_estado)s")
            params["filtro_estado"] = str(estado)

    where_clause = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    return where_clause, params


def obtener_kpis(
    perfil: str = "gerencia_general",
    region: str | None = None,
    filtros: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calcula dinámicamente los 6 indicadores oficiales en PostgreSQL:
    1. Ingresos: SUM(precio)
    2. Órdenes: COUNT(orden_id)
    3. Ticket Promedio: Ingresos / Órdenes
    4. Margen (%): ((Ingresos - SUM(costo)) / Ingresos) * 100
    5. Entregas a tiempo (%): (COUNT(a_tiempo) / COUNT(entregadas)) * 100
    6. Tasa de devolución (%): (COUNT(devueltas) / COUNT(ordenes)) * 100
    """
    where_sql, params = _construir_clausula_where(perfil, region, filtros)

    sql = f"""
        SELECT 
            COALESCE(COUNT(f.orden_id), 0) AS ordenes,
            COALESCE(SUM(f.precio), 0) AS ingresos,
            COALESCE(SUM(f.costo), 0) AS costos,
            CASE 
                WHEN COUNT(f.orden_id) > 0 THEN COALESCE(SUM(f.precio), 0) / COUNT(f.orden_id)
                ELSE 0 
            END AS ticket_promedio,
            CASE 
                WHEN COALESCE(SUM(f.precio), 0) > 0 THEN 
                    ((COALESCE(SUM(f.precio), 0) - COALESCE(SUM(f.costo), 0)) / SUM(f.precio)) * 100.0
                ELSE 0 
            END AS margen_pct,
            COALESCE(COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END), 0) AS total_entregadas,
            COALESCE(COUNT(CASE 
                WHEN f.estado = 'Entregada' 
                     AND s.tiempo_prometido_h IS NOT NULL 
                     AND f.horas_reales <= s.tiempo_prometido_h 
                THEN 1 
            END), 0) AS entregadas_a_tiempo,
            CASE 
                WHEN COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END) > 0 THEN 
                    (COUNT(CASE 
                        WHEN f.estado = 'Entregada' 
                             AND s.tiempo_prometido_h IS NOT NULL 
                             AND f.horas_reales <= s.tiempo_prometido_h 
                        THEN 1 
                    END)::numeric / COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END)) * 100.0
                ELSE 0 
            END AS entregas_a_tiempo_pct,
            COALESCE(COUNT(CASE WHEN f.estado = 'Devuelta' THEN 1 END), 0) AS total_devueltas,
            CASE 
                WHEN COUNT(f.orden_id) > 0 THEN 
                    (COUNT(CASE WHEN f.estado = 'Devuelta' THEN 1 END)::numeric / COUNT(f.orden_id)) * 100.0
                ELSE 0 
            END AS tasa_devolucion_pct
        FROM fact_ordenes f
        JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
        JOIN dim_cliente c ON f.cliente_id = c.cliente_id
        JOIN dim_servicio s ON f.servicio_id = s.servicio_id
        JOIN dim_centro cnt ON f.centro_id = cnt.centro_id
        {where_sql}
    """
    res = consultar(sql, params, uno=True) or {}
    
    ordenes = int(res.get("ordenes") or 0)
    ingresos = float(res.get("ingresos") or 0)
    costos = float(res.get("costos") or 0)
    ticket_promedio = float(res.get("ticket_promedio") or 0)
    margen_pct = float(res.get("margen_pct") or 0)
    entregadas_a_tiempo_pct = float(res.get("entregas_a_tiempo_pct") or 0)
    tasa_devolucion_pct = float(res.get("tasa_devolucion_pct") or 0)
    total_entregadas = int(res.get("total_entregadas") or 0)
    entregadas_a_tiempo = int(res.get("entregadas_a_tiempo") or 0)
    total_devueltas = int(res.get("total_devueltas") or 0)

    return {
        "ordenes": ordenes,
        "ingresos": ingresos,
        "costos": costos,
        "utilidad": ingresos - costos,
        "ticket_promedio": ticket_promedio,
        "margen_pct": round(margen_pct, 2),
        "entregas_a_tiempo_pct": round(entregadas_a_tiempo_pct, 2),
        "tasa_devolucion_pct": round(tasa_devolucion_pct, 2),
        "total_entregadas": total_entregadas,
        "entregadas_a_tiempo": entregadas_a_tiempo,
        "total_devueltas": total_devueltas,
    }


def obtener_serie_temporal(
    perfil: str = "gerencia_general",
    region: str | None = None,
    filtros: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Devuelve la evolución mensual (2022-2025) de Ingresos, Costos, Órdenes y Margen.
    Etiqueta el mes atípico (2024-08).
    """
    where_sql, params = _construir_clausula_where(perfil, region, filtros)

    sql = f"""
        SELECT 
            t.anio,
            t.mes,
            t.nombre_mes,
            CONCAT(t.anio, '-', LPAD(t.mes::text, 2, '0')) AS periodo,
            COUNT(f.orden_id) AS ordenes,
            COALESCE(SUM(f.precio), 0) AS ingresos,
            COALESCE(SUM(f.costo), 0) AS costos,
            CASE 
                WHEN COALESCE(SUM(f.precio), 0) > 0 THEN 
                    ((SUM(f.precio) - SUM(f.costo)) / SUM(f.precio)) * 100.0
                ELSE 0 
            END AS margen_pct,
            COUNT(CASE WHEN f.estado = 'Entregada' AND s.tiempo_prometido_h IS NOT NULL AND f.horas_reales <= s.tiempo_prometido_h THEN 1 END) AS a_tiempo,
            COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END) AS entregadas,
            COUNT(CASE WHEN f.estado = 'Devuelta' THEN 1 END) AS devueltas
        FROM fact_ordenes f
        JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
        JOIN dim_cliente c ON f.cliente_id = c.cliente_id
        JOIN dim_servicio s ON f.servicio_id = s.servicio_id
        JOIN dim_centro cnt ON f.centro_id = cnt.centro_id
        {where_sql}
        GROUP BY t.anio, t.mes, t.nombre_mes
        ORDER BY t.anio, t.mes
    """
    filas = consultar(sql, params)
    ords = [float(f["ordenes"]) for f in filas]
    if ords:
        prom_ord = sum(ords) / len(ords)
        var_ord = sum((x - prom_ord) ** 2 for x in ords) / len(ords)
        desv_ord = math.sqrt(var_ord) if var_ord > 0 else 1.0
    else:
        prom_ord, desv_ord = 0.0, 1.0

    for f in filas:
        f["ingresos"] = float(f["ingresos"])
        f["costos"] = float(f["costos"])
        f["margen_pct"] = round(float(f["margen_pct"]), 2)
        z = (float(f["ordenes"]) - prom_ord) / desv_ord
        f["z_score"] = round(z, 2)
        f["es_anomalia"] = bool(z > 2.0 and f["mes"] != 12)
    return filas


def obtener_por_servicio(
    perfil: str = "gerencia_general",
    region: str | None = None,
    filtros: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Desempeño por Tipo de Servicio (dim_servicio)."""
    where_sql, params = _construir_clausula_where(perfil, region, filtros)

    sql = f"""
        SELECT 
            s.servicio_id,
            s.tipo_servicio,
            COUNT(f.orden_id) AS ordenes,
            COALESCE(SUM(f.precio), 0) AS ingresos,
            COALESCE(SUM(f.costo), 0) AS costos,
            CASE 
                WHEN COALESCE(SUM(f.precio), 0) > 0 THEN 
                    ((SUM(f.precio) - SUM(f.costo)) / SUM(f.precio)) * 100.0
                ELSE 0 
            END AS margen_pct,
            CASE 
                WHEN COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END) > 0 THEN 
                    (COUNT(CASE WHEN f.estado = 'Entregada' AND s.tiempo_prometido_h IS NOT NULL AND f.horas_reales <= s.tiempo_prometido_h THEN 1 END)::numeric / 
                     COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END)) * 100.0
                ELSE 0 
            END AS entregas_a_tiempo_pct
        FROM fact_ordenes f
        JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
        JOIN dim_cliente c ON f.cliente_id = c.cliente_id
        JOIN dim_servicio s ON f.servicio_id = s.servicio_id
        JOIN dim_centro cnt ON f.centro_id = cnt.centro_id
        {where_sql}
        GROUP BY s.servicio_id, s.tipo_servicio
        ORDER BY ingresos DESC
    """
    filas = consultar(sql, params)
    for f in filas:
        f["ingresos"] = float(f["ingresos"])
        f["costos"] = float(f["costos"])
        f["margen_pct"] = round(float(f["margen_pct"]), 2)
        f["entregas_a_tiempo_pct"] = round(float(f["entregas_a_tiempo_pct"]), 2)
    return filas


def obtener_por_centro(
    perfil: str = "gerencia_general",
    region: str | None = None,
    filtros: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Desempeño por Centro Logístico (dim_centro)."""
    where_sql, params = _construir_clausula_where(perfil, region, filtros)

    sql = f"""
        SELECT 
            cnt.centro_id,
            cnt.nombre_centro,
            cnt.region,
            COUNT(f.orden_id) AS ordenes,
            COALESCE(SUM(f.precio), 0) AS ingresos,
            COALESCE(SUM(f.costo), 0) AS costos,
            CASE 
                WHEN COALESCE(SUM(f.precio), 0) > 0 THEN 
                    ((SUM(f.precio) - SUM(f.costo)) / SUM(f.precio)) * 100.0
                ELSE 0 
            END AS margen_pct,
            CASE 
                WHEN COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END) > 0 THEN 
                    (COUNT(CASE WHEN f.estado = 'Entregada' AND s.tiempo_prometido_h IS NOT NULL AND f.horas_reales <= s.tiempo_prometido_h THEN 1 END)::numeric / 
                     COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END)) * 100.0
                ELSE 0 
            END AS entregas_a_tiempo_pct
        FROM fact_ordenes f
        JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
        JOIN dim_cliente c ON f.cliente_id = c.cliente_id
        JOIN dim_servicio s ON f.servicio_id = s.servicio_id
        JOIN dim_centro cnt ON f.centro_id = cnt.centro_id
        {where_sql}
        GROUP BY cnt.centro_id, cnt.nombre_centro, cnt.region
        ORDER BY ordenes DESC
    """
    filas = consultar(sql, params)
    for f in filas:
        f["ingresos"] = float(f["ingresos"])
        f["costos"] = float(f["costos"])
        f["margen_pct"] = round(float(f["margen_pct"]), 2)
        f["entregas_a_tiempo_pct"] = round(float(f["entregas_a_tiempo_pct"]), 2)
    return filas


def obtener_detalle_ordenes(
    perfil: str = "gerencia_general",
    region: str | None = None,
    filtros: dict[str, Any] | None = None,
    limit: int = 15,
    offset: int = 0,
) -> dict[str, Any]:
    """Detalle operativo paginado para el Nivel 3 del Tablero."""
    where_sql, params = _construir_clausula_where(perfil, region, filtros)

    sql_conteo = f"""
        SELECT COUNT(f.orden_id) 
        FROM fact_ordenes f
        JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
        JOIN dim_cliente c ON f.cliente_id = c.cliente_id
        JOIN dim_servicio s ON f.servicio_id = s.servicio_id
        JOIN dim_centro cnt ON f.centro_id = cnt.centro_id
        {where_sql}
    """
    total = int(escalar(sql_conteo, params) or 0)

    params_query = dict(params)
    params_query["lim"] = limit
    params_query["off"] = offset

    sql_filas = f"""
        SELECT 
            f.orden_id,
            t.fecha,
            c.region AS region_cliente,
            SUBSTRING(c.nit_hash, 1, 8) || '...' AS cliente_hash,
            s.tipo_servicio,
            cnt.nombre_centro,
            f.peso_kg,
            f.precio,
            f.costo,
            (f.precio - f.costo) AS margen_individual,
            CASE 
                WHEN f.precio > 0 THEN ((f.precio - f.costo) / f.precio) * 100.0
                ELSE 0 
            END AS margen_individual_pct,
            f.estado,
            f.horas_reales,
            s.tiempo_prometido_h,
            CASE 
                WHEN f.estado = 'Entregada' AND s.tiempo_prometido_h IS NOT NULL THEN 
                    CASE WHEN f.horas_reales <= s.tiempo_prometido_h THEN 1 ELSE 0 END
                ELSE NULL
            END AS a_tiempo
        FROM fact_ordenes f
        JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
        JOIN dim_cliente c ON f.cliente_id = c.cliente_id
        JOIN dim_servicio s ON f.servicio_id = s.servicio_id
        JOIN dim_centro cnt ON f.centro_id = cnt.centro_id
        {where_sql}
        ORDER BY f.orden_id DESC
        LIMIT %(lim)s OFFSET %(off)s
    """
    filas = consultar(sql_filas, params_query)
    for f in filas:
        f["fecha_str"] = str(f["fecha"])
        f["precio"] = float(f["precio"]) if f["precio"] is not None else 0.0
        f["costo"] = float(f["costo"]) if f["costo"] is not None else 0.0
        f["margen_individual"] = float(f["margen_individual"]) if f["margen_individual"] is not None else 0.0
        f["margen_individual_pct"] = round(float(f["margen_individual_pct"]), 1) if f["margen_individual_pct"] is not None else 0.0
        f["peso_kg"] = float(f["peso_kg"]) if f["peso_kg"] is not None else 0.0
        f["horas_reales"] = float(f["horas_reales"]) if f["horas_reales"] is not None else None

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "filas": filas,
    }


def obtener_regiones_disponibles() -> list[str]:
    """Obtiene la lista canónica de regiones registradas en dim_cliente."""
    filas = consultar("SELECT DISTINCT region FROM dim_cliente WHERE region IS NOT NULL ORDER BY region")
    return [f["region"] for f in filas]


def obtener_opciones_filtros() -> dict[str, Any]:
    """Valores disponibles para los selectores desplegables de filtrado global."""
    anios = [r["anio"] for r in consultar("SELECT DISTINCT anio FROM dim_tiempo ORDER BY anio")]
    meses = consultar("SELECT DISTINCT mes, nombre_mes FROM dim_tiempo ORDER BY mes")
    servicios = consultar("SELECT servicio_id, tipo_servicio FROM dim_servicio ORDER BY tipo_servicio")
    centros = consultar("SELECT centro_id, nombre_centro, region FROM dim_centro ORDER BY nombre_centro")
    regiones = obtener_regiones_disponibles()
    estados = [r["estado"] for r in consultar("SELECT DISTINCT estado FROM fact_ordenes WHERE estado IS NOT NULL ORDER BY estado")]

    return {
        "anios": anios,
        "meses": meses,
        "servicios": servicios,
        "centros": centros,
        "regiones": regiones,
        "estados": estados,
    }


def verificar_integridad_regional() -> dict[str, Any]:
    """PRUEBA DE INTEGRIDAD DE CONTROL DE ACCESO (Criterio Crítico de Aprobación):
    Ejecuta el cálculo de los 6 KPIs para Gerencia General (Total Nacional)
    y para cada una de las 5 regiones individuales con la cláusula WHERE c.region = :region.
    Verifica matemáticamente que la suma de las partes equivale con precisión exacta al total consolidado.
    """
    total_gerencia = obtener_kpis(perfil="gerencia_general")
    regiones = obtener_regiones_disponibles()

    filas_regiones = []
    suma_ordenes = 0
    suma_ingresos = 0.0
    suma_costos = 0.0
    suma_entregadas_a_tiempo = 0
    suma_total_entregadas = 0
    suma_devueltas = 0

    for r in regiones:
        k_r = obtener_kpis(perfil="gerente_regional", region=r)
        filas_regiones.append({
            "region": r,
            "ordenes": k_r["ordenes"],
            "ingresos": k_r["ingresos"],
            "costos": k_r["costos"],
            "ticket_promedio": k_r["ticket_promedio"],
            "margen_pct": k_r["margen_pct"],
            "entregas_a_tiempo_pct": k_r["entregas_a_tiempo_pct"],
            "tasa_devolucion_pct": k_r["tasa_devolucion_pct"],
            "total_entregadas": k_r["total_entregadas"],
            "entregadas_a_tiempo": k_r["entregadas_a_tiempo"],
            "total_devueltas": k_r["total_devueltas"],
        })
        suma_ordenes += k_r["ordenes"]
        suma_ingresos += k_r["ingresos"]
        suma_costos += k_r["costos"]
        suma_entregadas_a_tiempo += k_r["entregadas_a_tiempo"]
        suma_total_entregadas += k_r["total_entregadas"]
        suma_devueltas += k_r["total_devueltas"]

    ticket_promedio_suma = (suma_ingresos / suma_ordenes) if suma_ordenes > 0 else 0
    margen_pct_suma = ((suma_ingresos - suma_costos) / suma_ingresos * 100.0) if suma_ingresos > 0 else 0
    a_tiempo_pct_suma = (suma_entregadas_a_tiempo / suma_total_entregadas * 100.0) if suma_total_entregadas > 0 else 0
    devolucion_pct_suma = (suma_devueltas / suma_ordenes * 100.0) if suma_ordenes > 0 else 0

    totales_suma = {
        "ordenes": suma_ordenes,
        "ingresos": suma_ingresos,
        "costos": suma_costos,
        "ticket_promedio": ticket_promedio_suma,
        "margen_pct": round(margen_pct_suma, 2),
        "entregas_a_tiempo_pct": round(a_tiempo_pct_suma, 2),
        "tasa_devolucion_pct": round(devolucion_pct_suma, 2),
    }

    # Verificación de igualdad exacta
    coincide_ordenes = (suma_ordenes == total_gerencia["ordenes"])
    coincide_ingresos = (abs(suma_ingresos - total_gerencia["ingresos"]) < 0.01)
    coincide_costos = (abs(suma_costos - total_gerencia["costos"]) < 0.01)
    es_integro = coincide_ordenes and coincide_ingresos and coincide_costos

    return {
        "es_integro": es_integro,
        "total_gerencia": total_gerencia,
        "totales_suma": totales_suma,
        "regiones": filas_regiones,
        "diferencias": {
            "dif_ordenes": total_gerencia["ordenes"] - suma_ordenes,
            "dif_ingresos": total_gerencia["ingresos"] - suma_ingresos,
            "dif_costos": total_gerencia["costos"] - suma_costos,
        }
    }
