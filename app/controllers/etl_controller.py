"""Controlador de la API del ETL.

POST /api/cargar            sube el archivo (multipart) y arranca la carga en segundo plano
GET  /api/estado/<job_id>   progreso en vivo (logs, pasos, resultado)
GET  /api/resumen           datos para refrescar tarjetas, historial y descartes
GET  /api/logs              ultimos logs guardados
POST /api/reiniciar         vacia la base
"""
import threading
import time
import traceback
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from app.config import Config
from app.models import consultas, database
from app.services.etl_pipeline import EtlError, ejecutar_carga, registrar_ejecucion

bp = Blueprint("etl", __name__)

_EN_CURSO = threading.Lock()       # una sola carga a la vez (evita carreras / doble clic)
_JOBS: dict[str, dict] = {}


def _limpiar_jobs():
    for jid in list(_JOBS):
        if time.time() - _JOBS[jid]["inicio"] > 3600:
            _JOBS.pop(jid, None)


def _trabajar(job: dict, ruta: Path, nombre: str, borrar: bool) -> None:
    def log(msg):
        job["logs"].append(msg)

    def paso(n, datos):
        job["pasos"][n] = datos

    try:
        # Cosmetico: imita la consola de la captura (la carga real corre en este hilo).
        log("$ python etl/cargar.py")
        resultado = ejecutar_carga(ruta, nombre, Config.NIT_SALT, Config.PRIVATE_DIR, log=log, paso=paso)
        registrar_ejecucion(nombre, resultado, "\n".join(job["logs"]))
        job["resultado"] = {k: v for k, v in resultado.items() if k != "resumen"}
        job["estado"] = "ok"
    except EtlError as exc:
        log(f"ERROR: {exc}")
        job["error"], job["estado"] = str(exc), "error"
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        log(f"ERROR inesperado: {type(exc).__name__}: {exc}")
        job["error"], job["estado"] = f"{type(exc).__name__}: {exc}", "error"
    finally:
        if borrar:
            ruta.unlink(missing_ok=True)
        _EN_CURSO.release()


@bp.route("/cargar", methods=["POST"])
def cargar():
    if not _EN_CURSO.acquire(blocking=False):
        return jsonify(error="Ya hay una carga en curso. Espere a que termine."), 409
    iniciado = False      # si el hilo arranca, EL HILO libera el candado; si no, lo liberamos aqui
    try:
        _limpiar_jobs()
        archivo = request.files.get("archivo")
        if archivo and archivo.filename:
            ext = Path(archivo.filename).suffix.lower()
            if ext not in Config.EXTENSIONES_PERMITIDAS:
                return jsonify(error=f"Formato {ext or 'desconocido'} no permitido. Use .xlsx o .csv"), 400
            nombre = secure_filename(archivo.filename) or f"archivo{ext}"
            ruta = Config.UPLOAD_DIR / f"{uuid.uuid4().hex}_{nombre}"
            archivo.save(ruta)
            borrar = True
        else:
            ruta, nombre, borrar = Config.ARCHIVO_RESPALDO, Config.ARCHIVO_RESPALDO.name, False
            if not ruta.exists():
                return jsonify(error="No se seleccionó archivo y no existe data/PROYECTO_MotoExpres.xlsx"), 400

        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "estado": "corriendo", "logs": [], "pasos": {}, "resultado": None,
               "error": None, "inicio": time.time(), "archivo": nombre}
        _JOBS[job_id] = job
        threading.Thread(target=_trabajar, args=(job, ruta, nombre, borrar), daemon=True).start()
        iniciado = True
        return jsonify(job_id=job_id, archivo=nombre), 202
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify(error=f"{type(exc).__name__}: {exc}"), 500
    finally:
        if not iniciado:
            _EN_CURSO.release()


@bp.route("/estado/<job_id>")
def estado(job_id):
    job = _JOBS.get(job_id)
    if job is None:
        return jsonify(error="Trabajo no encontrado"), 404
    desde = request.args.get("desde", default=0, type=int)
    logs = job["logs"]
    return jsonify(
        estado=job["estado"], logs=logs[desde:], total_logs=len(logs),
        pasos=job["pasos"], resultado=job["resultado"], error=job["error"],
        segundos=round(time.time() - job["inicio"], 1),
    )


@bp.route("/resumen")
def resumen():
    try:
        return jsonify(consultas.datos_carga() | {"ultima": None}), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"{type(exc).__name__}: {exc}"), 500


@bp.route("/logs")
def logs():
    try:
        return jsonify(logs=consultas.logs_recientes(10))
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=str(exc)), 500


@bp.route("/reiniciar", methods=["POST"])
def reiniciar():
    if not _EN_CURSO.acquire(blocking=False):
        return jsonify(error="No se puede reiniciar mientras hay una carga en curso."), 409
    try:
        database.reiniciar_base()
        return jsonify(ok=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify(error=f"{type(exc).__name__}: {exc}"), 500
    finally:
        _EN_CURSO.release()
