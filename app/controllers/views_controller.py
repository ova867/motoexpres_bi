"""Controlador de vistas: renderiza las 4 pantallas del Hito 1 con datos de PostgreSQL."""
from flask import Blueprint, redirect, render_template, url_for

from app.models import consultas
from app.services import quality_checker as qc

bp = Blueprint("views", __name__)

ESCALA_K = 7  # el ancho de la barra de k va de 0 a 7; la meta (5) queda marcada


def _barra_k(k: int) -> dict:
    return {"ancho": max(min(k / ESCALA_K * 100, 100), 3 if k else 0), "meta": qc.META_K / ESCALA_K * 100}


def _intentar(fn, *args):
    """Si la BD no responde, la pantalla se muestra igual con el error visible."""
    try:
        return fn(*args), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}".strip()


@bp.route("/")
def inicio():
    return redirect(url_for("views.carga"))


@bp.route("/carga")
def carga():
    datos, error = _intentar(consultas.datos_carga)
    return render_template("carga.html", activo="carga", d=datos, error_bd=error)


@bp.route("/calidad")
def calidad():
    def cargar():
        ultima = consultas.ultima_ejecucion()
        diag = ((ultima or {}).get("resumen") or {}).get("diagnostico")
        return {"ultima": ultima, "diag": diag, "cuarentena": consultas.total_cuarentena(),
                "chips": qc.CHIP_DECISION}
    datos, error = _intentar(cargar)
    return render_template("calidad.html", activo="calidad", d=datos, error_bd=error)


@bp.route("/privacidad")
def privacidad():
    def cargar():
        ultima = consultas.ultima_ejecucion()
        priv = ((ultima or {}).get("resumen") or {}).get("proteger") or {}
        antes = priv.get("k_antes")
        despues = qc.k_desde_bd() or priv.get("k_despues")   # EN VIVO desde dim_cliente
        return {
            "antes": antes, "despues": despues,
            "barra_antes": _barra_k(antes["k"]) if antes else None,
            "barra_despues": _barra_k(despues["k"]) if despues else None,
            "meta": qc.META_K,
            "columnas": qc.CLASIFICACION_COLUMNAS,
            "hay_corrida": ultima is not None,
        }
    datos, error = _intentar(cargar)
    return render_template("privacidad.html", activo="privacidad", d=datos, error_bd=error)


@bp.route("/modelo")
def modelo():
    def cargar():
        return {"conteos": consultas.conteos_modelo(), "huerfanos": consultas.huerfanos()}
    datos, error = _intentar(cargar)
    return render_template("modelo.html", activo="modelo", d=datos, error_bd=error)


@bp.route("/tablero")
def tablero():
    def cargar():
        from app.services import analytics_service as asvc
        from flask import request
        region = request.args.get("region")
        if region in ("gerencia", "todos", "all", ""):
            region = None
        asvc.registrar_acceso(
            pantalla="Tablero",
            usuario="lgomez" if region else "gerencia",
            rol=f"Gerente regional · {region}" if region else "Gerencia general",
            region=region,
        )
        return asvc.obtener_datos_tablero(region=region)
    datos, error = _intentar(cargar)
    return render_template("tablero.html", activo="tablero", d=datos, error_bd=error)


@bp.route("/explorar")
def explorar():
    def cargar():
        from app.services import analytics_service as asvc
        from flask import request
        region = request.args.get("region")
        asvc.registrar_acceso(
            pantalla="Explorar",
            usuario="lgomez" if region else "gerencia",
            rol=f"Gerente regional · {region}" if region else "Gerencia general",
            region=region,
        )
        return asvc.obtener_datos_explorar(region_seleccionada=region)
    datos, error = _intentar(cargar)
    return render_template("explorar.html", activo="explorar", d=datos, error_bd=error)


@bp.route("/alertas")
def alertas():
    def cargar():
        from app.services import analytics_service as asvc
        asvc.registrar_acceso(pantalla="Alertas", usuario="gerencia", rol="Gerencia general")
        return asvc.obtener_datos_alertas()
    datos, error = _intentar(cargar)
    return render_template("alertas.html", activo="alertas", d=datos, error_bd=error)


@bp.route("/accesos")
def accesos():
    def cargar():
        from app.services import analytics_service as asvc
        asvc.registrar_acceso(pantalla="Accesos", usuario="auditor1", rol="Auditor")
        return asvc.obtener_datos_accesos()
    datos, error = _intentar(cargar)
    return render_template("accesos.html", activo="accesos", d=datos, error_bd=error)

