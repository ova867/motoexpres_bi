"""Conexion, pool y utilidades psycopg2."""
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None
_config = None


def init_pool(config) -> None:
    """Crea el pool de conexiones (se conecta de forma perezosa)."""
    global _config
    _config = config


def _crear_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            1, 10,
            host=_config.DB_HOST,
            port=_config.DB_PORT,
            dbname=_config.DB_NAME,
            user=_config.DB_USER,
            password=_config.DB_PASSWORD,
            client_encoding="UTF8",
            options="-c timezone=America/Bogota",
        )
    return _pool


@contextmanager
def conexion():
    """Entrega una conexion; hace commit al salir bien y rollback si hay error."""
    pool = _crear_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def consultar(sql: str, params=None, uno: bool = False):
    """SELECT -> lista de dicts (o un dict si uno=True)."""
    with conexion() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        filas = cur.fetchall()
    if uno:
        return filas[0] if filas else None
    return [dict(f) for f in filas]


def escalar(sql: str, params=None):
    """Devuelve el primer valor de la primera fila."""
    with conexion() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        fila = cur.fetchone()
    return fila[0] if fila else None


def ejecutar_script(ruta) -> None:
    with open(ruta, encoding="utf-8") as fh:
        sql = fh.read()
    with conexion() as conn, conn.cursor() as cur:
        cur.execute(sql)


def asegurar_esquema() -> None:
    """Aplica schema.sql (es idempotente: CREATE ... IF NOT EXISTS)."""
    ejecutar_script(_config.SCHEMA_SQL)


def reiniciar_base() -> None:
    """Vacia TODAS las tablas del proyecto y reinicia contadores."""
    with conexion() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE fact_ordenes, stg_fact_ordenes, stg_rechazos, etl_log, "
            "dim_tiempo, dim_cliente, dim_servicio, dim_centro RESTART IDENTITY CASCADE"
        )
    asegurar_esquema()  # vuelve a sembrar el miembro 'Sin servicio' (-1)
