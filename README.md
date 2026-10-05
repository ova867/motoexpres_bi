# MotoExpres BI · Hito 1 — Los datos entran y quedan guardados

Aplicación web (Flask · MVC) + PostgreSQL. Carga un `.xlsx` o `.csv` desde el navegador, ejecuta el ETL
(14 reglas DAMA, normalización, k-anonimato, hash del NIT) y guarda un esquema en estrella.
**La carga es idempotente**: ejecutarla dos veces deja 0 filas nuevas y el mismo total (182.490).


python run.py
```

Abra <http://127.0.0.1:5000>.









