"""Connector DuckDB sobre los CSV locales.

Registra las tres tablas lógicas (`precios`, `sku`, `ventas`) como VISTAS que
apuntan a los CSV con `read_csv_auto`. DuckDB escanea el archivo bajo demanda
y hace pushdown de filtros y LIMIT, así que NO se cargan miles de filas a
memoria: cada query lee solo lo necesario.

La conexión se abre en modo `read_only` cuando existe una base persistente.
Para el caso de vistas sobre CSV usamos una base in-memory (las vistas no
copian datos) o un archivo .duckdb con las vistas ya definidas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from app.config import settings
from app.data_access.connector import DataConnector
from app.security.sql_guard import sanitize


def _view_ddl(data_dir: Path) -> list[str]:
    """DDL de las vistas lógicas sobre los CSV.

    `read_csv_auto` infiere tipos; forzamos las fechas y COD_SKU a tipos
    estables para que los joins y filtros del LLM sean predecibles.
    """
    precios = (data_dir / settings.precios_csv).as_posix()
    sku = (data_dir / settings.sku_csv).as_posix()
    venta = (data_dir / settings.venta_csv).as_posix()
    return [
        f"""
        CREATE OR REPLACE VIEW precios AS
        SELECT
            CAST(COD_SKU AS VARCHAR)          AS COD_SKU,
            DESC_SKU, DESC_DIVISION, DESC_DEPARTAMENTO, DESC_SUBDEPARTAMENTO,
            TIPO_KVI, TIPO_KVC,
            CAST(fecha AS DATE)               AS fecha,
            CAST(precio_propio AS DOUBLE)     AS precio_propio,
            CAST(precio_competencia AS DOUBLE) AS precio_competencia,
            CAST(unidades_totales AS DOUBLE)  AS unidades_totales,
            CAST(venta_total AS DOUBLE)       AS venta_total
        FROM read_csv_auto('{precios}', header=true)
        """,
        f"""
        CREATE OR REPLACE VIEW sku AS
        SELECT
            CAST(COD_SKU AS VARCHAR)          AS COD_SKU,
            DESC_SKU, DESC_MARCA, DESC_PROVEEDOR,
            DESC_DIVISION, DESC_DEPARTAMENTO, DESC_SUBDEPARTAMENTO,
            DESC_CLASE, DESC_SUBCLASE, DESC_ESTADO,
            CAST(F_PRECIO_COSTO AS DOUBLE)    AS F_PRECIO_COSTO,
            CAST(ELASTICIDAD AS DOUBLE)       AS ELASTICIDAD
        FROM read_csv_auto('{sku}', header=true)
        """,
        f"""
        CREATE OR REPLACE VIEW ventas AS
        SELECT
            CAST(id_diaventa AS DATE)         AS id_diaventa,
            CAST(cod_sku AS VARCHAR)          AS cod_sku,
            CAST(id_sku AS VARCHAR)           AS id_sku,
            CAST(VTA_SI AS DOUBLE)            AS VTA_SI,
            CAST(UNIDADES AS DOUBLE)          AS UNIDADES
        FROM read_csv_auto('{venta}', header=true)
        """,
    ]


class DuckDBConnector(DataConnector):
    """Implementación local con DuckDB + vistas sobre CSV."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or settings.data_dir
        # In-memory: las vistas no copian datos, solo apuntan a los CSV.
        self._con = duckdb.connect(database=":memory:")
        for ddl in _view_ddl(self._data_dir):
            self._con.execute(ddl)

    def run_select(self, sql: str) -> list[dict[str, Any]]:
        safe_sql = sanitize(sql, settings.max_query_rows)
        cur = self._con.execute(safe_sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def sku_exists(self, cod_sku: str) -> bool:
        row = self._con.execute(
            "SELECT 1 FROM sku WHERE COD_SKU = ? LIMIT 1",
            [str(cod_sku)],
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._con.close()


# --- Fábrica: único punto donde se elige el backend --------------------------
# El día que exista BigQuery: agregar BigQueryConnector y cambiar SOLO esto.
def get_connector() -> DataConnector:
    return DuckDBConnector()
