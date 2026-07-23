"""Connector SQLite sobre los CSV locales.

Alternativa a DuckDB que NO depende de un wheel nativo externo: `sqlite3` viene
incluido en Python, así que no lo bloquea Smart App Control. Carga los 3 CSV a
una base SQLite (por defecto un archivo `data/pricing.sqlite`) y ejecuta ahí el
SQL generado por el LLM.

Mantiene la misma interfaz `DataConnector`: el resto de la app no cambia. El
único costo es que el SQL usa dialecto SQLite (fechas ISO como texto, strftime)
en vez de DuckDB/BigQuery.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings
from app.data_access.connector import DataConnector
from app.security.sql_guard import sanitize

# Definición de cada tabla lógica: (columnas destino, mapeo desde el CSV).
# columns: lista de (nombre, tipo_sqlite, es_real). num=True -> castear a float.
_TABLES: dict[str, dict[str, Any]] = {
    "precios": {
        "csv": lambda: settings.precios_path,
        "columns": [
            ("COD_SKU", "TEXT", False), ("DESC_SKU", "TEXT", False),
            ("DESC_DIVISION", "TEXT", False), ("DESC_DEPARTAMENTO", "TEXT", False),
            ("DESC_SUBDEPARTAMENTO", "TEXT", False), ("TIPO_KVI", "TEXT", False),
            ("TIPO_KVC", "TEXT", False), ("fecha", "TEXT", False),
            ("precio_propio", "REAL", True), ("precio_competencia", "REAL", True),
            ("unidades_totales", "REAL", True), ("venta_total", "REAL", True),
        ],
    },
    "sku": {
        "csv": lambda: settings.sku_path,
        "columns": [
            ("COD_SKU", "TEXT", False), ("DESC_SKU", "TEXT", False),
            ("DESC_MARCA", "TEXT", False), ("DESC_PROVEEDOR", "TEXT", False),
            ("DESC_DIVISION", "TEXT", False), ("DESC_DEPARTAMENTO", "TEXT", False),
            ("DESC_SUBDEPARTAMENTO", "TEXT", False), ("DESC_CLASE", "TEXT", False),
            ("DESC_SUBCLASE", "TEXT", False), ("DESC_ESTADO", "TEXT", False),
            ("F_PRECIO_COSTO", "REAL", True), ("ELASTICIDAD", "REAL", True),
        ],
    },
    "ventas": {
        "csv": lambda: settings.venta_path,
        "columns": [
            ("id_diaventa", "TEXT", False), ("cod_sku", "TEXT", False),
            ("id_sku", "TEXT", False), ("VTA_SI", "REAL", True),
            ("UNIDADES", "REAL", True),
        ],
    },
}


def _to_float(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _load_table(con: sqlite3.Connection, name: str, spec: dict[str, Any]) -> None:
    cols = spec["columns"]
    col_defs = ", ".join(f'"{c}" {t}' for c, t, _ in cols)
    con.execute(f'DROP TABLE IF EXISTS "{name}"')
    con.execute(f'CREATE TABLE "{name}" ({col_defs})')

    placeholders = ", ".join("?" for _ in cols)
    insert = f'INSERT INTO "{name}" VALUES ({placeholders})'

    csv_path: Path = spec["csv"]()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            row = []
            for cname, _t, is_num in cols:
                val = r.get(cname)
                row.append(_to_float(val) if is_num else (val if val != "" else None))
            rows.append(row)
        con.executemany(insert, rows)
    # Índice por la clave de join más usada.
    key = "COD_SKU" if name in ("precios", "sku") else "cod_sku"
    con.execute(f'CREATE INDEX "idx_{name}_sku" ON "{name}" ("{key}")')


def build_sqlite(db_path: Path | None = None) -> Path:
    """(Re)construye la base SQLite a partir de los CSV. Devuelve la ruta."""
    target = db_path or settings.sqlite_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    con = sqlite3.connect(str(target))
    try:
        for name, spec in _TABLES.items():
            _load_table(con, name, spec)
        con.commit()
    finally:
        con.close()
    return target


class SqliteConnector(DataConnector):
    def __init__(self, db_path: Path | None = None, build_if_missing: bool = True) -> None:
        self._path = db_path or settings.sqlite_path
        if build_if_missing and not self._path.exists():
            build_sqlite(self._path)
        # Solo lectura: barrera adicional a nivel de motor.
        self._con = sqlite3.connect(
            f"file:{self._path.as_posix()}?mode=ro", uri=True, check_same_thread=False
        )
        self._con.row_factory = sqlite3.Row

    def run_select(self, sql: str) -> list[dict[str, Any]]:
        safe_sql = sanitize(sql, settings.max_query_rows)
        cur = self._con.execute(safe_sql)
        return [dict(row) for row in cur.fetchall()]

    def sku_exists(self, cod_sku: str) -> bool:
        row = self._con.execute(
            "SELECT 1 FROM sku WHERE COD_SKU = ? LIMIT 1", [str(cod_sku)]
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._con.close()


# --- Fábrica: único punto donde se elige el backend -------------------------
def get_connector() -> DataConnector:
    return SqliteConnector()
