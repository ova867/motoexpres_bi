"""Controlador API REST para analítica y control de accesos (Hito 2).
100% DINÁMICO: Consulta exclusivamente la base de datos PostgreSQL.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.models import analytics_queries as aq
from app.services import analytics_service as asvc

bp = Blueprint("analytics", __name__)


def _extraer_contexto():
    """Extrae el perfil y región del usuario desde query params, cabeceras o sesión."""
    perfil = request.args.get("perfil") or session.get("perfil", "gerencia_general")
    region = request.args.get("region") or session.get("region")
    
    # Si el perfil no es gerente_regional, ignorar region
    if perfil != "gerente_regional":
        region = None

    filtros = {
        "anio": request.args.get("anio"),
        "mes": request.args.get("mes"),
        "servicio_id": request.args.get("servicio_id"),
        "centro_id": request.args.get("centro_id"),
        "estado": request.args.get("estado"),
    }
    return perfil, region, filtros


@bp.route("/tablero", methods=["GET"])
def api_tablero():
    """Datos consolidados para el Tablero con RLS parametrizado."""
    try:
        perfil, region, filtros = _extraer_contexto()
        data = asvc.obtener_datos_tablero(region=region)
        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/kpis", methods=["GET"])
def api_kpis():
    """Cálculo dinámico de los 6 indicadores oficiales en PostgreSQL."""
    try:
        perfil, region, filtros = _extraer_contexto()
        kpis = aq.obtener_kpis(perfil=perfil, region=region, filtros=filtros)
        return jsonify({"kpis": kpis, "perfil": perfil, "region": region})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/ordenes", methods=["GET"])
def api_ordenes():
    """Nivel 3: Detalle operativo paginado de envíos con RLS."""
    try:
        perfil, region, filtros = _extraer_contexto()
        limit = min(int(request.args.get("limit", 15)), 100)
        offset = max(int(request.args.get("offset", 0)), 0)
        detalle = aq.obtener_detalle_ordenes(
            perfil=perfil, region=region, filtros=filtros, limit=limit, offset=offset
        )
        return jsonify(detalle)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/fichas-tecnicas", methods=["GET"])
def api_fichas_tecnicas():
    """Fichas metodológicas de los 6 indicadores oficiales con sus valores reales calculados."""
    try:
        perfil, region, filtros = _extraer_contexto()
        kpis = aq.obtener_kpis(perfil=perfil, region=region, filtros=filtros)
        fichas_base = [
            {"id": "ingresos", "nombre": "Ingresos Brutos", "formula": "SUM(precio)", "meta": "> 0", "unidad": "$ COP"},
            {"id": "ordenes", "nombre": "Volumen de Órdenes", "formula": "COUNT(orden_id)", "meta": "Crecimiento", "unidad": "órdenes"},
            {"id": "ticket_promedio", "nombre": "Ticket Promedio", "formula": "Ingresos / Órdenes", "meta": "> $50.000", "unidad": "$ COP"},
            {"id": "margen_pct", "nombre": "Margen Operativo", "formula": "((Ingresos - Costos) / Ingresos) * 100", "meta": "> 45%", "unidad": "%"},
            {"id": "entregas_a_tiempo_pct", "nombre": "Nivel de Servicio (OTIF/SLA)", "formula": "(Entregadas a Tiempo / Entregadas Totales) * 100", "meta": ">= 85%", "unidad": "%"},
            {"id": "tasa_devolucion_pct", "nombre": "Tasa de Devolución", "formula": "(Devueltas / Total Órdenes) * 100", "meta": "<= 5%", "unidad": "%"},
        ]
        for f in fichas_base:
            f["valor_actual"] = kpis.get(f["id"])
        return jsonify({"fichas": fichas_base, "kpis": kpis})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/anomalia", methods=["GET"])
def api_anomalia():
    """Detección y caracterización dinámica del mes atípico detectado estadísticamente."""
    try:
        datos_alertas = asvc.obtener_datos_alertas()
        serie = datos_alertas.get("serie_ordenes") or []
        mes_anomalo = next((m for m in serie if m.get("es_anomalo")), None)

        if not mes_anomalo and serie:
            mes_anomalo = max(serie, key=lambda x: x["ordenes"])

        if mes_anomalo:
            mes_num = mes_anomalo["mes"]
            filas_mismo_mes = aq.consultar("""
                SELECT 
                    t.anio, 
                    COUNT(f.orden_id) AS ordenes,
                    COALESCE(SUM(f.precio), 0) AS ingresos,
                    COALESCE(SUM(f.costo), 0) AS costos,
                    ROUND((COUNT(CASE WHEN f.estado = 'Entregada' AND f.horas_reales <= s.tiempo_prometido_h THEN 1 END)::numeric / 
                           NULLIF(COUNT(CASE WHEN f.estado = 'Entregada' THEN 1 END), 0)) * 100, 1) AS a_tiempo_pct,
                    ROUND((COUNT(CASE WHEN f.estado = 'Devuelta' THEN 1 END)::numeric / NULLIF(COUNT(f.orden_id), 0)) * 100, 1) AS devolucion_pct
                FROM fact_ordenes f
                JOIN dim_tiempo t ON f.fecha_id = t.fecha_id
                JOIN dim_servicio s ON f.servicio_id = s.servicio_id
                WHERE t.mes = %s
                GROUP BY t.anio
                ORDER BY t.anio
            """, (mes_num,))
            for r in filas_mismo_mes:
                r["ingresos"] = float(r["ingresos"])
                r["costos"] = float(r["costos"])
                r["es_anomalo"] = (r["anio"] == mes_anomalo["anio"])
        else:
            filas_mismo_mes = []

        return jsonify({
            "mes_detectado": mes_anomalo,
            "comparativa_historica": filas_mismo_mes,
            "alertas": datos_alertas.get("alertas", []),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/integridad-accesos", methods=["GET"])
def api_integridad():
    """Prueba matemática de Row-Level Security: Suma(Regiones) == Total Gerencia."""
    try:
        resultado = aq.verificar_integridad_regional()
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/set-perfil", methods=["POST"])
def api_set_perfil():
    """Guarda el perfil activo en la sesión para navegación persistente."""
    data = request.get_json(silent=True) or {}
    perfil = data.get("perfil", "gerencia_general")
    region = data.get("region")
    session["perfil"] = perfil
    session["region"] = region
    return jsonify({"ok": True, "perfil": perfil, "region": region})
