"""Validación y saneamiento de SQL generado por el LLM.

Regla de oro: nunca confiar en el SQL del LLM. Este módulo:
  - rechaza cualquier cosa que no sea un único SELECT / WITH...SELECT,
  - bloquea DDL/DML y palabras peligrosas,
  - fuerza un LIMIT como red de seguridad.

No pretende ser un parser SQL completo; es una lista de negación estricta
sobre statements de una sola sentencia. El connector (solo lectura) es la
segunda barrera.
"""

from __future__ import annotations

import re

# Palabras/tokens prohibidos (DDL, DML, PRAGMA, acceso a archivos, etc.).
_FORBIDDEN = (
    "insert", "update", "delete", "drop", "create", "alter", "truncate",
    "replace", "merge", "grant", "revoke", "attach", "detach", "copy",
    "export", "import", "install", "load", "pragma", "set", "call",
    "vacuum", "read_csv", "read_parquet", "read_json",
)

# Funciones que tocan el sistema de archivos / procesos (DuckDB y SQLite).
# Se bloquea cualquier llamada read_*(...) (read_csv, read_parquet, ...),
# glob(...) y load_extension(...) de SQLite.
_FORBIDDEN_FUNC_PATTERNS = (
    r"\bread_\w*\s*\(",
    r"\bglob\s*\(",
    r"\bload_extension\s*\(",
)


class UnsafeSQLError(ValueError):
    """El SQL generado no pasó la validación de seguridad."""


def _strip_comments(sql: str) -> str:
    # Elimina comentarios de línea (--...) y de bloque (/* ... */).
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def validate_select(sql: str) -> str:
    """Valida que `sql` sea un único SELECT seguro. Devuelve el SQL normalizado.

    Lanza `UnsafeSQLError` si algo huele mal.
    """
    if not sql or not sql.strip():
        raise UnsafeSQLError("SQL vacío.")

    cleaned = _strip_comments(sql).strip().rstrip(";").strip()

    # Una sola sentencia: no debe quedar ';' interno.
    if ";" in cleaned:
        raise UnsafeSQLError("Se permite una sola sentencia SQL.")

    lowered = cleaned.lower()

    # Debe empezar con SELECT o WITH (CTE que termina en SELECT).
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise UnsafeSQLError("Solo se permiten consultas SELECT.")

    # Lista de negación por palabra completa.
    tokens = set(re.findall(r"[a-z_]+", lowered))
    hits = tokens.intersection(_FORBIDDEN)
    if hits:
        raise UnsafeSQLError(f"Tokens prohibidos en el SQL: {sorted(hits)}")

    for pattern in _FORBIDDEN_FUNC_PATTERNS:
        m = re.search(pattern, lowered)
        if m:
            raise UnsafeSQLError(f"Función no permitida: {m.group(0).strip()}")

    return cleaned


def enforce_limit(sql: str, max_rows: int) -> str:
    """Garantiza un LIMIT <= max_rows. Si no hay LIMIT, lo agrega.

    Asume que `sql` ya pasó `validate_select` (una sola sentencia SELECT).
    """
    cleaned = sql.strip().rstrip(";").strip()
    m = re.search(r"\blimit\s+(\d+)\b", cleaned, flags=re.IGNORECASE)
    if m:
        current = int(m.group(1))
        if current > max_rows:
            cleaned = (
                cleaned[: m.start()]
                + f"LIMIT {max_rows}"
                + cleaned[m.end():]
            )
        return cleaned
    return f"{cleaned}\nLIMIT {max_rows}"


def sanitize(sql: str, max_rows: int) -> str:
    """Atajo: valida y fuerza LIMIT en un solo paso."""
    return enforce_limit(validate_select(sql), max_rows)
