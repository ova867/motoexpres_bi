"""Fabrica de la aplicacion Flask (MVC)."""
from flask import Flask

from app.config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    Config.UPLOAD_DIR.mkdir(exist_ok=True)
    Config.PRIVATE_DIR.mkdir(exist_ok=True)

    from app.models import database
    database.init_pool(Config)
    try:
        database.asegurar_esquema()
    except Exception as exc:  # la app abre igual y las vistas muestran el error
        print(f"[AVISO] No se pudo verificar el esquema: {exc}")

    from app.controllers.views_controller import bp as views_bp
    from app.controllers.etl_controller import bp as etl_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(etl_bp, url_prefix="/api")

    @app.template_filter("miles")
    def miles(valor):
        """12345 -> '12.345' (formato es-CO)."""
        if valor is None:
            return "–"
        try:
            return f"{int(round(float(valor))):,}".replace(",", ".")
        except (TypeError, ValueError):
            return str(valor)

    @app.template_filter("decimal")
    def decimal(valor, dec=1):
        return f"{float(valor):.{dec}f}".replace(".", ",")

    return app
