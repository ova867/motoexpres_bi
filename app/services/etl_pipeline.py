"""Pipeline ETL de MotoExpres (Hito 1).

  1 EXTRAER     lee .xlsx (todas las hojas) o .csv (solo fact_ordenes)
  2 VALIDAR     14 reglas DAMA (conteos sobre el archivo original)
  3 TRANSFORMAR corrige, marca, elimina duplicados y separa la cuarentena
  4 PROTEGER    retira datos personales, seudonimiza NIT, mide k-anonimato
  5 CARGAR      COPY masivo -> stg_fact_ordenes -> INSERT ... ON CONFLICT DO NOTHING

IDEMPOTENTE: ejecutarlo N veces sobre el mismo archivo deja la base igual
(0 filas nuevas). La garantia la da la llave primaria orden_id + ON CONFLICT.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from psycopg2.extras import Json, execute_values

from app.models.database import conexion
from app.services import quality_checker as qc

COLUMNAS_STG = [
    "orden_id", "fecha_id", "cliente_id", "servicio_id", "centro_id", "precio",
    "costo", "peso_kg", "distancia_km", "estado", "horas_reales", "marcas",
]
COLUMNAS_OBLIGATORIAS = [
    "orden_id", "fecha_id", "cliente_id", "servicio_id", "centro_id", "precio",
    "costo", "peso_kg", "distancia_km", "estado", "horas_reales",
]
HOJAS = ["fact_ordenes", "dim_cliente", "dim_servicio", "dim_centro", "dim_tiempo"]

# Tal cual lo pide el enunciado (E5): un unico INSERT ... SELECT idempotente
SQL_INSERT_FACT = """
INSERT INTO fact_ordenes (orden_id, fecha_id, cliente_id, servicio_id, centro_id,
                          precio, costo, peso_kg, distancia_km, estado, horas_reales, marcas)
SELECT orden_id, fecha_id, cliente_id, servicio_id, centro_id,
       precio, costo, peso_kg, distancia_km, estado, horas_reales, marcas
FROM stg_fact_ordenes
ON CONFLICT (orden_id) DO NOTHING
"""
# E'\t' (y no '\t') para que PostgreSQL reciba un unico caracter TAB
SQL_COPY = (
    "COPY stg_fact_ordenes (" + ", ".join(COLUMNAS_STG) + ") "
    "FROM STDIN WITH CSV HEADER DELIMITER E'\\t'"
)
SALT_POR_DEFECTO = "motoexpres-sal-de-desarrollo"


class EtlError(Exception):
    """Error esperado (archivo mal formado, dimensiones ausentes...)."""


def fmt(n) -> str:
    """12345 -> '12.345' (miles con punto, como en las capturas)."""
    return f"{int(n):,}".replace(",", ".")


def seg(x: float) -> str:
    """3.14 -> '3,1' (decimal con coma)."""
    return f"{x:.1f}".replace(".", ",")


def _py(o):
    """default= para json: numpy/pandas -> tipos nativos."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if o is pd.NA or o is pd.NaT:
        return None
    return str(o)


def _dumps(o) -> str:
    return json.dumps(o, default=_py, ensure_ascii=False)


# ==========================================================================
# 1. EXTRAER
# ==========================================================================
def _motor_excel() -> str:
    try:
        import python_calamine  # noqa: F401
        return "calamine"
    except ImportError:
        return "openpyxl"


def _minusculas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _leer_xlsx(ruta: Path, log) -> tuple[dict, str]:
    motor = _motor_excel()
    try:
        hojas = pd.read_excel(ruta, sheet_name=None, dtype=object, engine=motor)
    except Exception:
        if motor == "openpyxl":
            raise
        motor = "openpyxl"
        hojas = pd.read_excel(ruta, sheet_name=None, dtype=object, engine=motor)
    hojas = {str(k).strip().lower(): _minusculas(v) for k, v in hojas.items()}
    return {k: v for k, v in hojas.items() if k in HOJAS}, motor


def _leer_csv(ruta: Path) -> pd.DataFrame:
    with open(ruta, "rb") as fh:
        primera = fh.read(8192).decode("utf-8", "ignore").splitlines()[0]
    sep = max([",", ";", "\t", "|"], key=primera.count)
    try:
        df = pd.read_csv(ruta, sep=sep, dtype=object, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(ruta, sep=sep, dtype=object, encoding="latin-1")
    df = _minusculas(df)
    # En CSV todo llega como texto: devolvemos a numerico lo que lo sea, y dejamos
    # como texto solo lo que no (p. ej. precio "$ 69.159,00"), igual que en el Excel.
    for col in ("precio", "costo"):
        if col in df.columns:
            conv = pd.to_numeric(df[col], errors="coerce")
            df[col] = conv.where(conv.notna(), df[col])
    for col in ("orden_id", "fecha_id", "cliente_id", "servicio_id", "centro_id",
                "peso_kg", "distancia_km", "horas_reales", "horas_prometidas", "entrega_a_tiempo"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def extraer(ruta: Path, log) -> tuple[dict, str]:
    ext = ruta.suffix.lower()
    if ext == ".csv":
        return {"fact_ordenes": _leer_csv(ruta)}, "csv"
    if ext == ".xlsx":
        return _leer_xlsx(ruta, log)
    raise EtlError(f"Formato no soportado: {ext}. Use .xlsx o .csv")


def _validar_fact(f: pd.DataFrame) -> None:
    faltan = [c for c in COLUMNAS_OBLIGATORIAS if c not in f.columns]
    if faltan:
        raise EtlError("A fact_ordenes le faltan columnas: " + ", ".join(faltan))
    malos = num_ids_invalidos(f["orden_id"])
    if malos:
        raise EtlError(f"orden_id vacío o no numérico en {malos} filas: no se puede garantizar idempotencia")


def num_ids_invalidos(serie: pd.Series) -> int:
    return int(qc.num(serie).isna().sum())


# ==========================================================================
# Referencias (llaves validas): del archivo si trae la dimension, si no de la BD
# ==========================================================================
def _consultar_bd(sql: str) -> list[tuple]:
    with conexion() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def construir_referencias(hojas: dict) -> qc.Referencias:
    def ids(hoja, col, sql):
        if hoja in hojas and col in hojas[hoja].columns:
            return set(qc.num(hojas[hoja][col]).dropna().astype(int))
        return {int(r[0]) for r in _consultar_bd(sql)}

    clientes = ids("dim_cliente", "cliente_id", "SELECT cliente_id FROM dim_cliente")
    servicios = ids("dim_servicio", "servicio_id", "SELECT servicio_id FROM dim_servicio") | {-1}
    centros = ids("dim_centro", "centro_id", "SELECT centro_id FROM dim_centro")
    fechas = ids("dim_tiempo", "fecha_id", "SELECT fecha_id FROM dim_tiempo")

    if "dim_tiempo" in hojas and "fecha" in hojas["dim_tiempo"].columns:
        cal = pd.to_datetime(hojas["dim_tiempo"]["fecha"], errors="coerce")
        fmin, fmax = cal.min(), cal.max()
    else:
        filas = _consultar_bd("SELECT min(fecha), max(fecha) FROM dim_tiempo")
        fmin, fmax = (pd.Timestamp(filas[0][0]), pd.Timestamp(filas[0][1])) if filas and filas[0][0] else (None, None)

    if not (clientes and centros and fechas) or fmin is None:
        raise EtlError(
            "La base no tiene dimensiones y el archivo no las trae. "
            "Cargue primero el .xlsx completo (hojas dim_cliente, dim_servicio, dim_centro, dim_tiempo)."
        )
    return qc.Referencias(clientes, servicios, centros, fechas, fmin, fmax)


# ==========================================================================
# 3. TRANSFORMAR
# ==========================================================================
def transformar(f: pd.DataFrame, a: qc.Analisis, ref: qc.Referencias):
    """Devuelve (limpio, rechazos, stats). No toca horas_reales vacias."""
    b = a.banderas
    w = pd.DataFrame({
        "orden_id": qc.num(f["orden_id"]),
        "fecha_id": qc.num(f["fecha_id"]),
        "cliente_id": a.cliente_num,
        "servicio_id": qc.num(f["servicio_id"]),
        "centro_id": qc.num(f["centro_id"]),
        "precio": a.precio_num.abs(),               # precio < 0 -> se corrige a positivo
        "costo": qc.num(f["costo"]),
        "peso_kg": qc.num(f["peso_kg"]),
        "distancia_km": qc.num(f["distancia_km"]),
        "estado": a.estado_norm,                    # 9 variantes -> 4
        "horas_reales": qc.num(f["horas_reales"]),  # vacias legitimas: NO se rellenan
    })

    # servicio vacio (o inexistente) -> miembro "Sin servicio" (-1), no se borra
    serv_malo = w["servicio_id"].isna() | ~w["servicio_id"].isin(ref.servicios)
    w["servicio_id"] = w["servicio_id"].where(~serv_malo, -1)

    # marcas: filas "Marcar" se conservan pero quedan senaladas
    marcas = pd.Series("", index=w.index, dtype=object)
    for nombre, mascara in (
        ("peso_cero", b["peso_cero"]),
        ("costo_mayor_precio", b["costo_mayor_precio"]),
        ("sin_servicio", serv_malo),
        ("distancia_vacia", b["distancia_vacia"]),
    ):
        marcas = marcas.where(~mascara, marcas + nombre + "|")
    w["marcas"] = marcas.str.rstrip("|").replace("", np.nan)

    # --- 1) duplicados exactos: se elimina, se deja una copia ---
    dup = b["dup_exacta"]
    stats = {"duplicados_eliminados": int(dup.sum())}
    w = w[~dup]

    # --- 2) cuarentena (en este orden de prioridad) ---
    repetido = w["orden_id"].duplicated(keep="first")
    condiciones = [repetido, b.loc[w.index, "fecha_invalida"],
                   b.loc[w.index, "cliente_inexistente"], b.loc[w.index, "centro_inexistente"]]
    nombres = ["orden_id_repetido", "fecha_fuera_rango", "cliente_inexistente", "centro_inexistente"]
    motivo = pd.Series(np.select(condiciones, nombres, default=""), index=w.index)

    idx_rech = motivo[motivo != ""].index
    detalle_src = f.loc[idx_rech].astype(object).where(f.loc[idx_rech].notna(), None)
    rechazos = pd.DataFrame({
        "orden_id": w.loc[idx_rech, "orden_id"].astype("int64"),
        "motivo": motivo[idx_rech],
        "detalle": [_dumps(r) for r in detalle_src.to_dict("records")],
    })
    for nombre in nombres:
        stats[nombre] = int((motivo == nombre).sum())
    stats["centros_inexistentes"] = sorted(
        int(x) for x in w.loc[motivo == "centro_inexistente", "centro_id"].dropna().unique()
    )

    limpio = w[motivo == ""].copy()
    for col in ("orden_id", "fecha_id", "cliente_id", "servicio_id", "centro_id"):
        limpio[col] = limpio[col].astype("int64")
    limpio = limpio[COLUMNAS_STG]
    stats["filas_limpias"] = int(len(limpio))
    return limpio, rechazos, stats


# ==========================================================================
# 4. PROTEGER (privacidad)
# ==========================================================================
def proteger_clientes(cli: pd.DataFrame, salt: str, dir_privada: Path, log):
    """Quita identificadores directos, seudonimiza el NIT y generaliza cuasi-identificadores."""
    for col in ("cliente_id", "nit", "region", "segmento", "fecha_alta"):
        if col not in cli.columns:
            raise EtlError(f"A dim_cliente le falta la columna {col}")

    k_antes = qc.k_anonimato(cli, qc.QUASI_ANTES)     # tal como llego el archivo
    ciudad_norm = qc.normalizar_ciudad(cli["ciudad"]) if "ciudad" in cli.columns else None
    ciudades = (int(cli["ciudad"].nunique()), int(ciudad_norm.nunique())) if ciudad_norm is not None else (0, 0)

    clave = (salt or SALT_POR_DEFECTO).encode("utf-8")
    nit = cli["nit"].astype(str).str.strip()
    nit_hash = nit.map(lambda x: hmac.new(clave, x.encode("utf-8"), hashlib.sha256).hexdigest())

    # tabla de equivalencias: SOLO local, nunca al repositorio (private/ esta en .gitignore)
    dir_privada.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"cliente_id": qc.num(cli["cliente_id"]).astype(int), "nit": nit, "nit_hash": nit_hash}) \
        .to_csv(dir_privada / "tabla_equivalencias_nit.csv", index=False, encoding="utf-8")

    anio = pd.to_datetime(cli["fecha_alta"], errors="coerce").dt.year.astype("Int64")
    limpio = pd.DataFrame({
        "cliente_id": qc.num(cli["cliente_id"]).astype("int64"),
        "nit_hash": nit_hash,
        "region": cli["region"].astype(str).str.strip(),
        "segmento": cli["segmento"].astype(str).str.strip(),
        "anio_alta": anio,
    })
    k_despues = qc.k_anonimato(limpio, qc.QUASI_DESPUES)
    k_despues["k_con_anio"] = qc.k_anonimato(limpio, qc.QUASI_DESPUES + ["anio_alta"])["k"]
    columnas = [c for c in qc.COLUMNAS_DIRECTAS if c in cli.columns]
    return limpio, {
        "columnas_retiradas": len(columnas), "lista": columnas,
        "k_antes": k_antes, "k_despues": k_despues, "ciudades": ciudades,
    }


# ==========================================================================
# 5. CARGAR
# ==========================================================================
def _a_filas(df: pd.DataFrame) -> list[tuple]:
    """DataFrame -> tuplas con tipos nativos de Python (psycopg2 no adapta numpy)."""
    obj = df.astype(object).where(df.notna(), None)
    return list(obj.itertuples(index=False, name=None))


def _dim_tiempo(d: pd.DataFrame) -> pd.DataFrame:
    n = lambda c: qc.num(d[c]).astype("int64")  # noqa: E731
    return pd.DataFrame({
        "fecha_id": n("fecha_id"), "fecha": pd.to_datetime(d["fecha"]).dt.date,
        "anio": n("anio"), "mes": n("mes"), "nombre_mes": d["nombre_mes"].astype(str),
        "mes_orden": n("mes_orden"), "trimestre": d["trimestre"].astype(str),
        "dia": n("dia"), "dia_semana": d["dia_semana"].astype(str),
        "dia_semana_orden": n("dia_semana_orden"), "es_finde": n("es_finde"),
    })


def _dim_servicio(d: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "servicio_id": qc.num(d["servicio_id"]).astype("int64"),
        "tipo_servicio": d["tipo_servicio"].astype(str),
        "tiempo_prometido_h": qc.num(d["tiempo_prometido_h"]).astype("Int64"),
        "precio_base": qc.num(d["precio_base"]),
    })


def _dim_centro(d: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "centro_id": qc.num(d["centro_id"]).astype("int64"),
        "nombre_centro": d["nombre_centro"].astype(str),
        "region": d["region"].astype(str).str.strip(),
        "capacidad_dia": qc.num(d["capacidad_dia"]).astype("Int64"),
    })


def _upsert(cur, tabla: str, df: pd.DataFrame, pk: str, actualizar: bool = False) -> None:
    cols = list(df.columns)
    if actualizar:
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != pk)
        conflicto = f"ON CONFLICT ({pk}) DO UPDATE SET {sets}"
    else:
        conflicto = f"ON CONFLICT ({pk}) DO NOTHING"
    execute_values(
        cur, f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES %s {conflicto}",
        _a_filas(df), page_size=2000,
    )


def cargar(hojas: dict, cliente_limpio, limpio: pd.DataFrame, rechazos: pd.DataFrame,
           nombre_archivo: str, log) -> dict:
    """Todo en UNA transaccion: o entra completo o no entra nada."""
    with conexion() as conn, conn.cursor() as cur:
        # dimensiones (pocas filas): DO NOTHING; dim_cliente se actualiza (hash consistente con private/)
        if "dim_tiempo" in hojas:
            _upsert(cur, "dim_tiempo", _dim_tiempo(hojas["dim_tiempo"]), "fecha_id")
        if "dim_servicio" in hojas:
            _upsert(cur, "dim_servicio", _dim_servicio(hojas["dim_servicio"]), "servicio_id")
        if "dim_centro" in hojas:
            _upsert(cur, "dim_centro", _dim_centro(hojas["dim_centro"]), "centro_id")
        if cliente_limpio is not None:
            _upsert(cur, "dim_cliente", cliente_limpio, "cliente_id", actualizar=True)

        # staging: TRUNCATE + COPY masivo desde memoria (nada de INSERT fila por fila)
        t = time.perf_counter()
        cur.execute("TRUNCATE stg_fact_ordenes")
        buf = io.StringIO()
        limpio.to_csv(buf, sep="\t", index=False, header=True, na_rep="")
        buf.seek(0)
        cur.copy_expert(SQL_COPY, buf)
        log(f"      · COPY masivo a stg_fact_ordenes: {fmt(len(limpio))} filas en "
            f"{seg(time.perf_counter() - t)} s")

        # un unico INSERT idempotente hacia la tabla de hechos
        t = time.perf_counter()
        cur.execute(SQL_INSERT_FACT)
        nuevas = cur.rowcount
        log(f"      · INSERT ... ON CONFLICT DO NOTHING en {seg(time.perf_counter() - t)} s")

        # cuarentena: UNIQUE (orden_id, motivo) evita duplicarla al re-ejecutar
        if len(rechazos):
            execute_values(
                cur,
                "INSERT INTO stg_rechazos (orden_id, motivo, detalle, archivo) VALUES %s "
                "ON CONFLICT (orden_id, motivo) DO NOTHING",
                [(int(r.orden_id), r.motivo, r.detalle, nombre_archivo) for r in rechazos.itertuples()],
            )
        cur.execute("TRUNCATE stg_fact_ordenes")      # no dejar 182 mil filas de sobra
        cur.execute("SELECT count(*) FROM fact_ordenes")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM stg_rechazos")
        en_cuarentena = cur.fetchone()[0]
    return {"nuevas": int(nuevas), "total": int(total), "cuarentena": int(en_cuarentena)}


# ==========================================================================
# ORQUESTADOR
# ==========================================================================
def ejecutar_carga(ruta: Path, nombre_archivo: str, salt: str, dir_privada: Path,
                   log=print, paso=lambda n, datos: None) -> dict:
    t0 = time.perf_counter()
    try:
        return _ejecutar(ruta, nombre_archivo, salt, dir_privada, log, paso, t0)
    except KeyError as exc:
        raise EtlError(f"Falta la columna o la hoja {exc}") from exc


def _ejecutar(ruta, nombre_archivo, salt, dir_privada, log, paso, t0) -> dict:
    # ---- 1. EXTRAER -------------------------------------------------------
    hojas, motor = extraer(ruta, log)
    if "fact_ordenes" not in hojas:
        raise EtlError("El archivo no tiene la hoja 'fact_ordenes'")
    fact = hojas["fact_ordenes"]
    _validar_fact(fact)
    n_leidas = len(fact)
    log(f"[1/5] Leyendo fact_ordenes… {fmt(n_leidas)} filas")
    if len(hojas) > 1:
        log("      · hojas: " + ", ".join(f"{k} ({fmt(len(v))})" for k, v in hojas.items()))
    tarjetas = [None] * 5
    tarjetas[0] = {"valor": fmt(n_leidas), "texto": "filas leídas de fact_ordenes"}
    paso(1, tarjetas[0])

    # ---- 2. VALIDAR -------------------------------------------------------
    ref = construir_referencias(hojas)
    diag, analisis = qc.diagnosticar(fact, ref, hojas.get("dim_cliente"))
    log(f"[2/5] Validando reglas… {fmt(diag['filas_con_problema'])} filas marcadas")
    b = analisis.banderas
    log(f"      · {fmt(b['dup_exacta'].sum())} duplicados · {fmt(b['precio_texto'].sum())} precios con $ · "
        f"{fmt(b['precio_negativo'].sum())} precios < 0 · {fmt(b['estado_variante'].sum())} estados")
    log(f"      · {fmt(diag['vacios_legitimos'])} horas_reales vacías legítimas (no se tocan)")
    tarjetas[1] = {"valor": f"{diag['n_reglas']} reglas",
                   "texto": f"{fmt(diag['filas_con_problema'])} filas con al menos un problema"}
    paso(2, tarjetas[1])

    # ---- 3. TRANSFORMAR ---------------------------------------------------
    limpio, rechazos, stats = transformar(fact, analisis, ref)
    log("[3/5] Transformando… ok")
    log(f"      · {fmt(stats['duplicados_eliminados'])} duplicados eliminados · "
        f"{fmt(len(rechazos))} filas a cuarentena · {fmt(stats['filas_limpias'])} filas listas")
    tarjetas[2] = {"valor": f"{fmt(diag['precios_convertidos'])} + {fmt(diag['estados_normalizados'])}",
                   "texto": "precios convertidos · estados normalizados"}
    paso(3, tarjetas[2])

    # ---- 4. PROTEGER ------------------------------------------------------
    cliente_limpio, priv = (None, None)
    if "dim_cliente" in hojas:
        cliente_limpio, priv = proteger_clientes(hojas["dim_cliente"], salt, dir_privada, log)
        if not salt:
            log("      ! NIT_SALT no está definido en .env: se usó una sal de desarrollo")
        ncols = priv["columnas_retiradas"]
        log(f"[4/5] Retirando datos personales… {ncols} columnas")
        log(f"      · k antes = {priv['k_antes']['k']} ({fmt(priv['k_antes']['unicos'])} únicos) → "
            f"k después = {priv['k_despues']['k']} ({fmt(priv['k_despues']['unicos'])} únicos)")
    else:
        ncols = 0
        log("[4/5] Retirando datos personales… (este archivo no trae dim_cliente)")
    tarjetas[3] = {"valor": f"{ncols} columnas", "texto": "de datos personales retiradas"}
    paso(4, tarjetas[3])

    # ---- 5. CARGAR --------------------------------------------------------
    log("[5/5] Cargando con ON CONFLICT DO NOTHING…")
    res = cargar(hojas, cliente_limpio, limpio, rechazos, nombre_archivo, log)
    log(f"      · filas nuevas: {fmt(res['nuevas'])} · total en fact_ordenes: {fmt(res['total'])}")
    tarjetas[4] = {"valor": fmt(res["total"]), "texto": "filas en fact_ordenes"}
    paso(5, tarjetas[4])

    duracion = time.perf_counter() - t0
    log(f"Listo en {seg(duracion)} s")

    # ---- bitacora ---------------------------------------------------------
    anio0, anio1 = ref.fecha_min.year, ref.fecha_max.year
    centros = stats["centros_inexistentes"]
    etiqueta_centro = (f"Centro {', '.join(map(str, centros))} no existe"
                       if 0 < len(centros) <= 3 else "Centro no existe")
    descartes = [
        {"motivo": "Duplicado exacto", "filas": stats["duplicados_eliminados"],
         "destino": "Eliminado (se deja una copia)", "chip": "rojo"},
        {"motivo": f"Fecha fuera de {anio0}–{anio1}", "filas": stats["fecha_fuera_rango"],
         "destino": "Enviado a cuarentena", "chip": "ambar"},
        {"motivo": "Cliente no existe", "filas": stats["cliente_inexistente"],
         "destino": "Enviado a cuarentena", "chip": "ambar"},
        {"motivo": etiqueta_centro, "filas": stats["centro_inexistente"],
         "destino": "Enviado a cuarentena", "chip": "ambar"},
    ]
    if stats["orden_id_repetido"]:
        descartes.append({"motivo": "orden_id repetido (distinto contenido)",
                          "filas": stats["orden_id_repetido"],
                          "destino": "Enviado a cuarentena", "chip": "ambar"})

    resumen = {
        "archivo": nombre_archivo, "motor_lectura": motor, "hojas": list(hojas),
        "tarjetas": tarjetas, "diagnostico": diag, "transformar": stats,
        "proteger": priv, "descartes": descartes,
        "filas_leidas": n_leidas, "insertadas": res["nuevas"],
        "total": res["total"], "cuarentena": res["cuarentena"],
    }
    return {"resumen": resumen, "nuevas": res["nuevas"], "total": res["total"],
            "filas_leidas": n_leidas, "duracion": round(duracion, 1)}


def registrar_ejecucion(nombre_archivo: str, resultado: dict, log_text: str) -> int:
    """Guarda la corrida en etl_log y clasifica la 'doble carga'."""
    with conexion() as conn, conn.cursor() as cur:
        cur.execute("SELECT total_en_base FROM etl_log ORDER BY id DESC LIMIT 1")
        previa = cur.fetchone()
        if resultado["nuevas"] == 0:
            doble = "no_duplico"
        elif previa is None:
            doble = "primera"
        else:
            doble = "nuevas"
        cur.execute(
            "INSERT INTO etl_log (archivo, filas_leidas, filas_nuevas, total_en_base, duracion_s, "
            "doble_carga, resumen, log_text) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (nombre_archivo, resultado["filas_leidas"], resultado["nuevas"], resultado["total"],
             resultado["duracion"], doble,
             Json(resultado["resumen"], dumps=_dumps), log_text),
        )
        return cur.fetchone()[0]
