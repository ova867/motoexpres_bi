"""Configuracion: todo sale de variables de entorno (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-no-usar-en-produccion")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME", "motoexpres_bi")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    NIT_SALT = os.getenv("NIT_SALT", "")

    BASE_DIR = BASE_DIR
    UPLOAD_DIR = BASE_DIR / "uploads"
    PRIVATE_DIR = BASE_DIR / "private"
    ARCHIVO_RESPALDO = BASE_DIR / "data" / "PROYECTO_MotoExpres.xlsx"
    EXTENSIONES_PERMITIDAS = {".xlsx", ".csv"}
    SCHEMA_SQL = BASE_DIR / "app" / "models" / "schema.sql"
