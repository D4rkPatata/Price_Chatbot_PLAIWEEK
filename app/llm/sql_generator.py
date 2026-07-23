"""LLM #1: traduce el encargo estructurado en consultas SQL seguras.

Flujo:
  build_task_prompt(input) -> texto del encargo
  generate_queries(...)    -> llama a Gemini (JSON) -> valida cada SQL con el guard
                              -> devuelve lista de queries listas para ejecutar

No ejecuta nada: solo produce SQL validado. La ejecución vive en el connector.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.data_access.schema_catalog import render_schema_for_prompt
from app.llm.llm_client import LLMClient
from app.security.sql_guard import UnsafeSQLError, sanitize

_PROMPT_PATH = Path(__file__).parent / "prompts" / "sql_system_prompt.txt"


@dataclass
class GeneratedQuery:
    nombre: str
    objetivo: str
    sql: str  # ya validado y con LIMIT forzado


def _system_prompt() -> str:
    raw = _PROMPT_PATH.read_text(encoding="utf-8")
    return raw.replace("{SCHEMA}", render_schema_for_prompt())


def build_task_prompt(
    *,
    cod_sku: str,
    precio_propuesto: float,
    fecha_inicio: str,
    fecha_fin: str,
) -> str:
    """Encargo concreto que ve el LLM #1 (los valores del usuario)."""
    return (
        "ENCARGO:\n"
        f"- SKU objetivo (COD_SKU): '{cod_sku}'\n"
        f"- Precio propuesto: {precio_propuesto}\n"
        f"- Vigencia propuesta: desde {fecha_inicio} hasta {fecha_fin}\n\n"
        "Genera las consultas SQL para recolectar los hechos necesarios y "
        "evaluar este cambio de precio. Responde solo el JSON especificado."
    )


def _parse_queries(raw: str) -> list[dict]:
    """Parsea la respuesta JSON del modelo, tolerando envoltura en ```json."""
    text = raw.strip()
    if text.startswith("```"):
        # quitar cerca de código ```json ... ```
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    data = json.loads(text)
    queries = data.get("queries", [])
    if not isinstance(queries, list) or not queries:
        raise ValueError("El LLM no devolvió ninguna query en 'queries'.")
    return queries


def generate_queries(
    *,
    cod_sku: str,
    precio_propuesto: float,
    fecha_inicio: str,
    fecha_fin: str,
    client: LLMClient | None = None,
) -> list[GeneratedQuery]:
    client = client or LLMClient()
    raw = client.generate(
        system_prompt=_system_prompt(),
        user_prompt=build_task_prompt(
            cod_sku=cod_sku,
            precio_propuesto=precio_propuesto,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        ),
        temperature=0.0,
        json=True,
    )

    result: list[GeneratedQuery] = []
    errors: list[str] = []
    for q in _parse_queries(raw):
        nombre = str(q.get("nombre", "sin_nombre"))
        sql = str(q.get("sql", ""))
        try:
            safe = sanitize(sql, settings.max_query_rows)
        except UnsafeSQLError as e:
            errors.append(f"{nombre}: {e}")
            continue
        result.append(
            GeneratedQuery(nombre=nombre, objetivo=str(q.get("objetivo", "")), sql=safe)
        )

    if not result:
        raise UnsafeSQLError(
            "Ninguna query generada pasó la validación. " + " | ".join(errors)
        )
    return result
