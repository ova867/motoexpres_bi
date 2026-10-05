-- =====================================================================
-- MotoExpres BI - Hito 1 - Esquema en estrella (PostgreSQL 13+)
-- Granularidad: UNA FILA = UNA ORDEN
-- Es idempotente: se puede ejecutar varias veces sin error.
-- =====================================================================

-- ---------- DIMENSIONES ----------------------------------------------
CREATE TABLE IF NOT EXISTS dim_tiempo (
    fecha_id          INTEGER      PRIMARY KEY,          -- yyyymmdd
    fecha             DATE         NOT NULL,
    anio              SMALLINT     NOT NULL,
    mes               SMALLINT     NOT NULL,
    nombre_mes        VARCHAR(15)  NOT NULL,
    mes_orden         SMALLINT     NOT NULL,
    trimestre         CHAR(2)      NOT NULL,
    dia               SMALLINT     NOT NULL,
    dia_semana        VARCHAR(12)  NOT NULL,
    dia_semana_orden  SMALLINT     NOT NULL,
    es_finde          SMALLINT     NOT NULL
);

-- dim_cliente SIN datos personales: solo seudonimo del NIT y
-- cuasi-identificadores ya generalizados (region, segmento, anio).
CREATE TABLE IF NOT EXISTS dim_cliente (
    cliente_id  INTEGER      PRIMARY KEY,
    nit_hash    CHAR(64)     NOT NULL,                   -- HMAC-SHA256 del NIT
    region      VARCHAR(40)  NOT NULL,
    segmento    VARCHAR(20)  NOT NULL,
    anio_alta   SMALLINT
);

CREATE TABLE IF NOT EXISTS dim_servicio (
    servicio_id         INTEGER       PRIMARY KEY,
    tipo_servicio       VARCHAR(40)   NOT NULL,
    tiempo_prometido_h  INTEGER,
    precio_base         NUMERIC(14,2)
);

CREATE TABLE IF NOT EXISTS dim_centro (
    centro_id      INTEGER      PRIMARY KEY,
    nombre_centro  VARCHAR(60)  NOT NULL,
    region         VARCHAR(40)  NOT NULL,
    capacidad_dia  INTEGER
);

-- Miembro "Sin servicio": en lugar de borrar las ordenes con servicio_id vacio
INSERT INTO dim_servicio (servicio_id, tipo_servicio, tiempo_prometido_h, precio_base)
VALUES (-1, 'Sin servicio', NULL, NULL)
ON CONFLICT (servicio_id) DO NOTHING;

-- ---------- HECHOS ---------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_ordenes (
    orden_id      BIGINT        PRIMARY KEY,               -- clave de idempotencia (E5)
    fecha_id      INTEGER       NOT NULL REFERENCES dim_tiempo(fecha_id),
    cliente_id    INTEGER       NOT NULL REFERENCES dim_cliente(cliente_id),
    servicio_id   INTEGER       NOT NULL REFERENCES dim_servicio(servicio_id),
    centro_id     INTEGER       NOT NULL REFERENCES dim_centro(centro_id),
    precio        NUMERIC(14,2),
    costo         NUMERIC(14,2),
    peso_kg       NUMERIC(10,2),
    distancia_km  NUMERIC(10,2),
    estado        VARCHAR(20),
    horas_reales  NUMERIC(10,2),                           -- NULL legitimo si no hubo entrega
    marcas        TEXT                                     -- filas "Marcar": peso_cero|costo_mayor_precio|...
);
CREATE INDEX IF NOT EXISTS ix_fact_fecha    ON fact_ordenes (fecha_id);
CREATE INDEX IF NOT EXISTS ix_fact_cliente  ON fact_ordenes (cliente_id);
CREATE INDEX IF NOT EXISTS ix_fact_servicio ON fact_ordenes (servicio_id);
CREATE INDEX IF NOT EXISTS ix_fact_centro   ON fact_ordenes (centro_id);

-- ---------- STAGING (tabla intermedia para COPY masivo) ---------------
-- UNLOGGED: sin WAL, mucho mas rapida. Se vacia en cada ejecucion.
CREATE UNLOGGED TABLE IF NOT EXISTS stg_fact_ordenes (
    orden_id      BIGINT,
    fecha_id      INTEGER,
    cliente_id    INTEGER,
    servicio_id   INTEGER,
    centro_id     INTEGER,
    precio        NUMERIC(14,2),
    costo         NUMERIC(14,2),
    peso_kg       NUMERIC(10,2),
    distancia_km  NUMERIC(10,2),
    estado        VARCHAR(20),
    horas_reales  NUMERIC(10,2),
    marcas        TEXT
);

-- ---------- CUARENTENA ------------------------------------------------
-- Nada se borra sin dejar rastro: las filas rechazadas quedan aqui con su motivo.
CREATE TABLE IF NOT EXISTS stg_rechazos (
    id          SERIAL       PRIMARY KEY,
    orden_id    BIGINT       NOT NULL,
    motivo      VARCHAR(40)  NOT NULL,     -- fecha_fuera_rango | cliente_inexistente | centro_inexistente | orden_id_repetido
    detalle     TEXT,                      -- fila original en JSON
    archivo     VARCHAR(255),
    cargado_en  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_rechazo UNIQUE (orden_id, motivo)   -- re-ejecutar no duplica la cuarentena
);

-- ---------- BITACORA DE EJECUCIONES -----------------------------------
CREATE TABLE IF NOT EXISTS etl_log (
    id            SERIAL        PRIMARY KEY,
    ejecutado_en  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    archivo       VARCHAR(255),
    filas_leidas  INTEGER,
    filas_nuevas  INTEGER,
    total_en_base INTEGER,
    duracion_s    NUMERIC(8,1),
    doble_carga   VARCHAR(20),             -- primera | no_duplico | nuevas
    resumen       JSONB,
    log_text      TEXT
);
