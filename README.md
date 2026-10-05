# MotoExpres BI · Hito 1 — Los datos entran y quedan guardados

Aplicación web (Flask · MVC) + PostgreSQL. Carga un `.xlsx` o `.csv` desde el navegador, ejecuta el ETL
(14 reglas DAMA, normalización, k-anonimato, hash del NIT) y guarda un esquema en estrella.
**La carga es idempotente**: ejecutarla dos veces deja 0 filas nuevas y el mismo total (182.490).


python run.py
```

Abra <http://127.0.0.1:5000>.





# Guía de Git y GitHub (trabajo en equipo)

## A. Subir el proyecto por primera vez (una sola persona)

```bash
git config --global user.name  "Su Nombre"
git config --global user.email "correo-de-su-cuenta-github@ejemplo.com"

cd motoexpres_bi
git init -b main

# Verifique que los secretos y datos personales NO se rastrean
git status
git check-ignore -v .env private/tabla_equivalencias_nit.csv venv
# Debe imprimir una regla de .gitignore para cada ruta. Si .env aparece en "git status", deténgase.

git add .
git commit -m "feat: version inicial del Hito 1 (ETL idempotente, calidad, privacidad, modelo)"
```

En GitHub: **New repository** → nombre `motoexpres_bi` → **vacío** (sin README ni .gitignore) → Create.

```bash
git remote add origin https://github.com/USUARIO/motoexpres_bi.git
git push -u origin main
```

## B. Invitar a los compañeros

1. Repositorio → **Settings → Collaborators → Add people**.
2. Escriba el usuario o correo de cada integrante → **Add**.
3. Cada invitado acepta desde el correo (o en <https://github.com/USUARIO/motoexpres_bi/invitations>).
4. Recomendado: **Settings → Branches → Add rule** para `main` → *Require a pull request before merging*.

## C. Flujo de trabajo por ramas (para que TODOS tengan commits)

Cada integrante, una sola vez:

```bash
git clone https://github.com/USUARIO/motoexpres_bi.git
cd motoexpres_bi
git config user.name  "Su Nombre"
git config user.email "correo-de-su-cuenta-github@ejemplo.com"   # el MISMO que tiene en GitHub
copy .env.example .env      # y complete sus datos locales
```

Por cada tarea:

```bash
git checkout main
git pull origin main                      # partir siempre de lo último
git checkout -b feat/nombre-tarea         # ej.: feat/pantalla-calidad, docs/readme, fix/css-sidebar

# ...edite archivos...
git add app/templates/calidad.html
git commit -m "feat(calidad): agrega nota a la regla horas_reales"
git push -u origin feat/nombre-tarea
```

Luego en GitHub: **Compare & pull request** → describa el cambio → asigne a un compañero como *Reviewer* →
cuando lo apruebe, **Merge pull request** → **Delete branch**. Finalmente, cada quien actualiza su copia:

```bash
git checkout main
git pull origin main
```

Si aparece un conflicto al hacer `git pull`/merge: abra los archivos marcados con `<<<<<<<`, deje la versión correcta,
y ejecute `git add archivo && git commit`.

### Reparto sugerido para que todos tengan commits

| Integrante | Rama | Entrega |
|---|---|---|
| 1 | `feat/pipeline-etl` | `etl_pipeline.py`, pruebas de idempotencia |
| 2 | `feat/calidad` | `quality_checker.py`, `calidad.html` |
| 3 | `feat/privacidad` | k-anonimato, `privacidad.html`, tabla de equivalencias |
| 4 | `feat/modelo-y-docs` | `schema.sql`, `modelo.html`, README y bitácora |

### Reglas de oro

- **Nunca** haga commit de `.env`, de `private/` ni de archivos con datos personales. Si ocurre, avise al equipo:
  cambie las credenciales y la `NIT_SALT`, porque borrar el commit no borra el historial.
- Commits pequeños con mensajes claros (`feat:`, `fix:`, `docs:`, `refactor:`).
- Nadie hace `push` directo a `main`; todo entra por Pull Request.
- Para ver quién aportó qué: `git shortlog -sn` o la pestaña **Insights → Contributors** en GitHub.
