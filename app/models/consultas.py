"""Consultas de lectura que alimentan las vistas (todo sale de PostgreSQL)."""
from app.models.database import consultar, escalar


def ultima_ejecucion():
    return consultar(
        "SELECT id, archivo, filas_leidas, filas_nuevas, total_en_base, duracion_s, "
        "doble_carga, resumen, to_char(ejecutado_en, 'DD/MM/YYYY HH24:MI:SS') AS cuando "
        "FROM etl_log ORDER BY id DESC LIMIT 1",
        uno=True,
    )


def historial(limite: int = 10):
    return consultar(
        "SELECT * FROM (SELECT id, to_char(ejecutado_en, 'HH24:MI:SS') AS hora, "
        "filas_nuevas, total_en_base, doble_carga, duracion_s FROM etl_log "
        "ORDER BY id DESC LIMIT %s) t ORDER BY id",
        (limite,),
    )


def logs_recientes(corridas: int = 3) -> str:
    filas = consultar(
        "SELECT log_text FROM (SELECT id, log_text FROM etl_log ORDER BY id DESC LIMIT %s) t ORDER BY id",
        (corridas,),
    )
    return "\n\n".join(f["log_text"] for f in filas if f["log_text"])


def total_fact() -> int:
    return int(escalar("SELECT count(*) FROM fact_ordenes") or 0)


def total_cuarentena() -> int:
    return int(escalar("SELECT count(*) FROM stg_rechazos") or 0)


def conteos_modelo() -> dict:
    return consultar(
        "SELECT (SELECT count(*) FROM dim_tiempo) AS dim_tiempo, "
        "(SELECT count(*) FROM dim_cliente) AS dim_cliente, "
        "(SELECT count(*) FROM dim_servicio WHERE servicio_id <> -1) AS dim_servicio, "
        "(SELECT count(*) FROM dim_centro) AS dim_centro, "
        "(SELECT count(*) FROM fact_ordenes) AS fact_ordenes, "
        "(SELECT count(*) FROM fact_ordenes WHERE servicio_id = -1) AS sin_servicio",
        uno=True,
    )


def huerfanos() -> dict:
    """Revision de llaves DESPUES de cargar: ordenes sin su dimension."""
    return consultar(
        "SELECT "
        "(SELECT count(*) FROM fact_ordenes f LEFT JOIN dim_cliente d ON d.cliente_id = f.cliente_id "
        "  WHERE d.cliente_id IS NULL) AS cliente, "
        "(SELECT count(*) FROM fact_ordenes f LEFT JOIN dim_servicio d ON d.servicio_id = f.servicio_id "
        "  WHERE d.servicio_id IS NULL) AS servicio, "
        "(SELECT count(*) FROM fact_ordenes f LEFT JOIN dim_centro d ON d.centro_id = f.centro_id "
        "  WHERE d.centro_id IS NULL) AS centro, "
        "(SELECT count(*) FROM fact_ordenes f LEFT JOIN dim_tiempo d ON d.fecha_id = f.fecha_id "
        "  WHERE d.fecha_id IS NULL) AS fecha",
        uno=True,
    )


def datos_carga() -> dict:
    """Todo lo que necesita la pantalla 'Carga de datos' (render inicial y /api/resumen)."""
    ultima = ultima_ejecucion()
    resumen = (ultima or {}).get("resumen") or {}
    return {
        "ultima": ultima,
        "archivo": (ultima or {}).get("archivo"),
        "tarjetas": resumen.get("tarjetas"),
        "descartes": resumen.get("descartes", []),
        "historial": historial(),
        "logs": logs_recientes(),
        "total": total_fact(),
        "cuarentena": total_cuarentena(),
    }
