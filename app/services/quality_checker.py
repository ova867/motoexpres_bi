"""Diagnostico de calidad (DAMA-DMBOK), normalizaciones y k-anonimato.

Las MISMAS banderas (`analizar_hechos`) se usan para el diagnostico que ve el
profesor en la pantalla de Calidad y para decidir que se corrige, marca o
manda a cuarentena en el pipeline. Asi los conteos nunca se contradicen.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------
ESTADOS_CANON = {
    "entregada": "Entregada",
    "en transito": "En tránsito",
    "devuelta": "Devuelta",
    "cancelada": "Cancelada",
}
# Tabla de equivalencias explicita: INITCAP rompe "En tránsito" -> "En Tránsito"
ORDEN_ESTADOS = ["Entregada", "En tránsito", "Devuelta", "Cancelada"]

ORDEN_DIMENSIONES = [
    "Unicidad", "Validez", "Exactitud", "Consistencia",
    "Completitud", "Integridad", "Oportunidad", "Privacidad",
]
DIMENSIONES_DAMA_NUCLEO = {
    "Unicidad", "Validez", "Exactitud", "Consistencia", "Completitud", "Oportunidad",
}
CHIP_DECISION = {
    "Eliminar": "verde", "Corregir": "verde", "Retirar": "verde",
    "Marcar": "ambar", "Cuarentena": "ambar", "NO tocar": "azul",
}

CLASIFICACION_COLUMNAS = [
    {"columna": "nombre_cliente", "tipo": "directo", "accion": "Retirar"},
    {"columna": "nit",            "tipo": "directo", "accion": "Seudonimizar (hash)"},
    {"columna": "contacto",       "tipo": "directo", "accion": "Retirar"},
    {"columna": "email",          "tipo": "directo", "accion": "Retirar"},
    {"columna": "telefono",       "tipo": "directo", "accion": "Retirar"},
    {"columna": "region",         "tipo": "cuasi",   "accion": "Conservar"},
    {"columna": "ciudad",         "tipo": "cuasi",   "accion": "Retirar (queda región)"},
    {"columna": "sector",         "tipo": "cuasi",   "accion": "Retirar del análisis por cliente"},
    {"columna": "segmento",       "tipo": "cuasi",   "accion": "Conservar"},
    {"columna": "fecha_alta",     "tipo": "cuasi",   "accion": "Generalizar a año"},
]
COLUMNAS_DIRECTAS = [c["columna"] for c in CLASIFICACION_COLUMNAS if c["tipo"] == "directo"]
QUASI_ANTES = ["region", "ciudad", "sector", "segmento"]
QUASI_DESPUES = ["region", "segmento"]
META_K = 5


# --------------------------------------------------------------------------
# Utilidades de texto
# --------------------------------------------------------------------------
def sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def clave_texto(valor) -> str:
    """'  EN Tránsito ' -> 'en transito'."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return ""
    return re.sub(r"\s+", " ", sin_acentos(str(valor)).strip().lower())


def _visible(valor: str) -> str:
    """Muestra espacios sobrantes como '_' (como en la captura: 'Entregada_')."""
    return re.sub(r"^ +| +$", lambda m: "_" * len(m.group()), str(valor))


def normalizar_estado(serie: pd.Series) -> pd.Series:
    """Variantes -> 4 valores canonicos (por tabla de equivalencias, no INITCAP)."""
    mapa = {}
    for v in serie.dropna().unique():
        k = clave_texto(v)
        mapa[v] = ESTADOS_CANON.get(k, str(v).strip())
    return serie.map(mapa)


def normalizar_ciudad(serie: pd.Series) -> pd.Series:
    """Unifica 'CALI', 'cali', 'Cali ' -> 'Cali', 'MEDELLIN' -> 'Medellín'."""
    conteo = serie.dropna().astype(str).value_counts()
    elegido: dict[str, tuple] = {}
    for variante, n in conteo.items():
        k = clave_texto(variante)
        # preferimos la variante mas frecuente que conserve tildes y no este en mayuscula
        puntaje = (variante == variante.strip(), variante != variante.upper(),
                   variante != sin_acentos(variante), n)
        if k not in elegido or puntaje > elegido[k][0]:
            elegido[k] = (puntaje, variante.strip())
    return serie.map(lambda v: elegido.get(clave_texto(v), (None, v))[1] if pd.notna(v) else v)


def parsear_precio(serie: pd.Series) -> tuple[pd.Series, pd.Series]:
    """'$ 69.159,00' -> 69159.0. Devuelve (precio_numerico, era_texto)."""
    es_txt = serie.map(lambda v: isinstance(v, str))
    num = pd.to_numeric(serie.where(~es_txt), errors="coerce").astype("float64")
    if es_txt.any():
        limpio = (
            serie[es_txt].str.replace(r"[^\d,\-]", "", regex=True)
            .str.replace(",", ".", regex=False)
        )
        num.loc[es_txt] = pd.to_numeric(limpio, errors="coerce")
    return num, es_txt


def num(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


# --------------------------------------------------------------------------
# Referencias (llaves validas) y analisis por fila
# --------------------------------------------------------------------------
@dataclass
class Referencias:
    clientes: set
    servicios: set
    centros: set
    fechas: set
    fecha_min: pd.Timestamp
    fecha_max: pd.Timestamp


@dataclass
class Analisis:
    precio_num: pd.Series
    estado_norm: pd.Series
    cliente_num: pd.Series
    banderas: pd.DataFrame            # booleanas, una columna por regla de fila
    fecha_chk: pd.Series = field(default=None)


def analizar_hechos(f: pd.DataFrame, ref: Referencias) -> Analisis:
    """Evalua todas las reglas de nivel fila sobre fact_ordenes (sin modificarla)."""
    precio_num, precio_txt = parsear_precio(f["precio"])
    costo = num(f["costo"])
    peso = num(f["peso_kg"])
    estado_norm = normalizar_estado(f["estado"])
    cliente_num = num(f["cliente_id"])
    centro_num = num(f["centro_id"])
    fecha_id = num(f["fecha_id"])

    if "fecha_orden" in f.columns:
        fecha_chk = pd.to_datetime(f["fecha_orden"], errors="coerce")
    else:
        fecha_chk = pd.to_datetime(fecha_id.astype("Int64").astype(str), format="%Y%m%d", errors="coerce")

    b = pd.DataFrame(index=f.index)
    b["dup_exacta"] = f.duplicated(keep="first")
    b["precio_texto"] = precio_txt
    b["precio_negativo"] = precio_num < 0
    b["peso_cero"] = peso == 0
    b["costo_mayor_precio"] = (costo > precio_num) & (precio_num > 0)
    b["estado_variante"] = f["estado"].astype(str) != estado_norm.astype(str)
    b["servicio_vacio"] = f["servicio_id"].isna()
    b["distancia_vacia"] = f["distancia_km"].isna()
    b["horas_vacia"] = f["horas_reales"].isna()
    b["cliente_inexistente"] = ~cliente_num.isin(ref.clientes)
    b["centro_inexistente"] = ~centro_num.isin(ref.centros)
    b["fecha_invalida"] = (
        fecha_chk.isna() | (fecha_chk < ref.fecha_min) | (fecha_chk > ref.fecha_max)
        | ~fecha_id.isin(ref.fechas)
    )
    return Analisis(precio_num, estado_norm, cliente_num, b, fecha_chk)


# banderas que cuentan como "fila con problema" (horas_vacia es legitima aparte)
BANDERAS_PROBLEMA = [
    "dup_exacta", "precio_texto", "precio_negativo", "peso_cero", "costo_mayor_precio",
    "estado_variante", "servicio_vacio", "distancia_vacia",
    "cliente_inexistente", "centro_inexistente", "fecha_invalida",
]


# --------------------------------------------------------------------------
# Diagnostico DAMA (las 14 reglas)
# --------------------------------------------------------------------------
def _estado_antes_despues(estado_raw: pd.Series) -> list[dict]:
    grupos: dict[str, dict[str, int]] = {c: {} for c in ORDEN_ESTADOS}
    for valor, n in estado_raw.dropna().value_counts().items():
        canon = ESTADOS_CANON.get(clave_texto(valor), str(valor).strip())
        grupos.setdefault(canon, {})[str(valor)] = int(n)
    filas = []
    for canon, variantes in grupos.items():
        if not variantes:
            continue
        orden = sorted(variantes, key=lambda v: (v != canon, -variantes[v]))
        filas.append({"originales": [_visible(v) for v in orden], "queda": canon})
    return filas


def diagnosticar(f: pd.DataFrame, ref: Referencias, cliente_raw: pd.DataFrame | None):
    """Devuelve (diagnostico_dict, analisis). Conteos sobre el archivo ORIGINAL."""
    a = analizar_hechos(f, ref)
    b = a.banderas
    n = int(len(f))
    c = lambda col: int(b[col].sum())  # noqa: E731

    # vacios legitimos: horas_reales vacia en ordenes SIN entrega
    sin_entrega = a.estado_norm.fillna("") != "Entregada"
    vacios_legitimos = int((b["horas_vacia"] & sin_entrega).sum())
    entregadas_sin_horas = int((b["horas_vacia"] & ~sin_entrega).sum())
    nota_horas = ("Todas son órdenes devueltas, en tránsito o canceladas: no hubo entrega."
                  if entregadas_sin_horas == 0 else
                  f"{entregadas_sin_horas} son entregadas sin horas (revisar con el negocio); "
                  "el resto no tuvo entrega.")

    n_est_raw = int(f["estado"].dropna().nunique())
    n_est_can = int(a.estado_norm.dropna().nunique())

    if cliente_raw is not None and "ciudad" in cliente_raw.columns:
        v_ciudad = int(cliente_raw["ciudad"].dropna().nunique())
        v_ciudad_n = int(cliente_raw["ciudad"].dropna().map(clave_texto).nunique())
        n_clientes = int(len(cliente_raw))
    else:
        v_ciudad = v_ciudad_n = n_clientes = 0

    def r(dim, tabla, regla, filas, decision, nota=None):
        return {"dimension": dim, "tabla": tabla, "regla": regla, "filas": filas,
                "decision": decision, "chip": CHIP_DECISION[decision], "nota": nota}

    reglas = [
        r("Unicidad", "fact_ordenes", "fila completa", c("dup_exacta"), "Eliminar"),
        r("Validez", "fact_ordenes", 'precio con "$" y puntos', c("precio_texto"), "Corregir"),
        r("Exactitud", "fact_ordenes", "precio < 0", c("precio_negativo"), "Corregir"),
        r("Exactitud", "fact_ordenes", "peso_kg = 0", c("peso_cero"), "Marcar"),
        r("Exactitud", "fact_ordenes", "costo > precio", c("costo_mayor_precio"), "Marcar"),
        r("Consistencia", "fact_ordenes", f"estado · {n_est_raw} variantes → {n_est_can}",
          c("estado_variante"), "Corregir"),
        r("Consistencia", "dim_cliente", f"ciudad · {v_ciudad} variantes → {v_ciudad_n}",
          None, "Corregir"),
        r("Completitud", "fact_ordenes", "servicio_id vacío", c("servicio_vacio"), "Marcar"),
        r("Completitud", "fact_ordenes", "distancia_km vacía", c("distancia_vacia"), "Marcar"),
        r("Completitud", "fact_ordenes", "horas_reales vacía", c("horas_vacia"), "NO tocar", nota_horas),
        r("Integridad", "fact_ordenes", "cliente_id sin cliente", c("cliente_inexistente"), "Cuarentena"),
        r("Integridad", "fact_ordenes", "centro_id = 99" if _solo_99(f, b) else "centro_id sin centro",
          c("centro_inexistente"), "Cuarentena"),
        r("Oportunidad", "fact_ordenes", _txt_fechas_malas(a), c("fecha_invalida"), "Cuarentena"),
        r("Privacidad", "dim_cliente", "nombre, NIT, contacto, email, teléfono", n_clientes, "Retirar"),
    ]

    por_dim = {d: sum(1 for x in reglas if x["dimension"] == d) for d in ORDEN_DIMENSIONES}
    diag = {
        "filas_leidas": n,
        "n_reglas": len(reglas),
        "n_dimensiones": len({x["dimension"] for x in reglas} & DIMENSIONES_DAMA_NUCLEO),
        "filas_con_problema": int(b[BANDERAS_PROBLEMA].any(axis=1).sum()),
        "vacios_legitimos": vacios_legitimos,
        "reglas": reglas,
        "estado_antes_despues": _estado_antes_despues(f["estado"]),
        "reglas_por_dimension": por_dim,
        "precios_convertidos": c("precio_texto"),
        "estados_normalizados": c("estado_variante"),
    }
    return diag, a


def _solo_99(f: pd.DataFrame, b: pd.DataFrame) -> bool:
    malos = num(f.loc[b["centro_inexistente"], "centro_id"])
    return len(malos) > 0 and set(malos.dropna().astype(int)) == {99}


def _txt_fechas_malas(a: Analisis) -> str:
    anios = sorted({int(x.year) for x in a.fecha_chk[a.banderas["fecha_invalida"]].dropna()})
    if anios:
        return "fecha en " + " o ".join(str(x) for x in reversed(anios))
    return "fecha fuera del rango del calendario"


# --------------------------------------------------------------------------
# k-anonimato
# --------------------------------------------------------------------------
def k_anonimato(df: pd.DataFrame, columnas: list[str]) -> dict:
    """k = tamano del grupo mas pequeno que comparte los mismos cuasi-identificadores."""
    if df is None or df.empty or any(c not in df.columns for c in columnas):
        return {"k": 0, "unicos": 0, "total": 0, "grupos": 0, "columnas": columnas}
    tam = df.groupby(columnas, dropna=False).size()
    return {
        "k": int(tam.min()),
        "unicos": int((tam == 1).sum()),     # clientes que son su propio grupo
        "total": int(len(df)),
        "grupos": int(len(tam)),
        "columnas": columnas,
    }


def k_desde_bd() -> dict | None:
    """k 'despues de generalizar' calculado EN VIVO sobre dim_cliente de PostgreSQL."""
    from app.models.database import consultar

    filas = consultar("SELECT region, segmento, anio_alta FROM dim_cliente")
    if not filas:
        return None
    df = pd.DataFrame(filas)
    res = k_anonimato(df, QUASI_DESPUES)
    res["k_con_anio"] = k_anonimato(df, QUASI_DESPUES + ["anio_alta"])["k"]
    return res
