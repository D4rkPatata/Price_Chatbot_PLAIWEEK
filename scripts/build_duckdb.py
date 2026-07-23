"""Crea/inicializa la base DuckDB a partir de los CSV.

Uso:
    uv run python -m scripts.build_duckdb            # vistas sobre CSV (default)
    uv run python -m scripts.build_duckdb --materialize   # copia a tablas físicas
    uv run python -m scripts.build_duckdb --check    # solo smoke-test, no escribe

Por defecto crea VISTAS: no copia datos, DuckDB lee los CSV bajo demanda. Esto
es lo más fiel a "no cargar miles de filas a memoria". `--materialize` crea
tablas físicas dentro del .duckdb (útil si luego quieres borrar los CSV o
acelerar queries repetidas).
"""

from __future__ import annotations

import argparse
import sys

import duckdb

from app.config import settings
from app.data_access.duckdb_connector import _view_ddl


def _create_views(con: duckdb.DuckDBPyConnection) -> None:
    for ddl in _view_ddl(settings.data_dir):
        con.execute(ddl)


def _materialize(con: duckdb.DuckDBPyConnection) -> None:
    """Convierte cada vista en una tabla física con el mismo nombre."""
    for name in ("precios", "sku", "ventas"):
        con.execute(f"CREATE OR REPLACE TABLE {name}_tbl AS SELECT * FROM {name}")
        con.execute(f"DROP VIEW {name}")
        con.execute(f"ALTER TABLE {name}_tbl RENAME TO {name}")


def _smoke_test(con: duckdb.DuckDBPyConnection) -> None:
    checks = {
        "precios": "SELECT COUNT(*) FROM precios",
        "sku": "SELECT COUNT(*) FROM sku",
        "ventas": "SELECT COUNT(*) FROM ventas",
        "join_ok": (
            "SELECT COUNT(*) FROM precios p "
            "JOIN sku s ON p.COD_SKU = s.COD_SKU"
        ),
        "rango_ventas": "SELECT MIN(id_diaventa), MAX(id_diaventa) FROM ventas",
        "elasticidad_no_nula": "SELECT COUNT(*) FROM sku WHERE ELASTICIDAD IS NOT NULL",
    }
    print("\n== Smoke test ==")
    for label, q in checks.items():
        result = con.execute(q).fetchone()
        print(f"  {label:22s}: {result}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicializa la base DuckDB.")
    parser.add_argument("--materialize", action="store_true",
                        help="Crea tablas físicas en vez de vistas.")
    parser.add_argument("--check", action="store_true",
                        help="Solo corre el smoke-test en memoria, no escribe archivo.")
    args = parser.parse_args()

    # Validar que existan los CSV antes de nada.
    for path in (settings.precios_path, settings.sku_path, settings.venta_path):
        if not path.exists():
            print(f"ERROR: no existe el CSV esperado: {path}", file=sys.stderr)
            return 1

    if args.check:
        con = duckdb.connect(":memory:")
        _create_views(con)
        _smoke_test(con)
        con.close()
        print("\nOK (check en memoria).")
        return 0

    target = settings.duckdb_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()  # recrear limpio

    con = duckdb.connect(str(target))
    _create_views(con)
    if args.materialize:
        _materialize(con)
        print(f"Tablas físicas materializadas en: {target}")
    else:
        print(f"Vistas sobre CSV creadas en: {target}")
    _smoke_test(con)
    con.close()
    print(f"\nOK. Base lista: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
