"""Punto de entrada: python run.py"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        use_reloader=False,   # el hilo de carga no debe morir por un reinicio
        threaded=True,
    )
