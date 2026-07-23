"""LLM #2: convierte los resultados del SQL + reglas de negocio en un insight NL.

No ve el schema ni escribe SQL. Solo razona sobre los hechos ya calculados por
DuckDB y sobre las reglas de negocio de `settings`, y devuelve texto en español.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import settings
from app.llm.llm_client import LLMClient

_PROMPT_PATH = Path(__file__).parent / "prompts" / "insight_system_prompt.txt"


def _json_default(o: Any) -> Any:
    """Serializa tipos que DuckDB devuelve y json no maneja de fábrica."""
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def _business_rules_block() -> str:
    return (
        "REGLAS DE NEGOCIO:\n"
        f"- margen_minimo: {settings.margen_minimo} "
        f"({settings.margen_minimo * 100:.0f}% sobre precio de venta)\n"
        f"- margen_objetivo: {settings.margen_objetivo} "
        f"({settings.margen_objetivo * 100:.0f}%)\n"
        f"- paridad_tolerancia: {settings.paridad_tolerancia} "
        f"(±{settings.paridad_tolerancia * 100:.0f}% vs. competencia)"
    )


def build_insight_prompt(
    *,
    cod_sku: str,
    precio_propuesto: float,
    fecha_inicio: str,
    fecha_fin: str,
    facts: dict[str, list[dict[str, Any]]],
) -> str:
    """Arma el user prompt del LLM #2 con el encargo + hechos + reglas."""
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2, default=_json_default)
    return (
        "CAMBIO DE PRECIO PROPUESTO:\n"
        f"- SKU (COD_SKU): {cod_sku}\n"
        f"- Precio propuesto: {precio_propuesto}\n"
        f"- Vigencia: {fecha_inicio} a {fecha_fin}\n\n"
        f"{_business_rules_block()}\n\n"
        "HECHOS (resultados de las consultas SQL, por objetivo):\n"
        f"{facts_json}\n\n"
        "Redacta el insight siguiendo el formato indicado."
    )


def generate_insight(
    *,
    cod_sku: str,
    precio_propuesto: float,
    fecha_inicio: str,
    fecha_fin: str,
    facts: dict[str, list[dict[str, Any]]],
    client: LLMClient | None = None,
) -> str:
    client = client or LLMClient()
    return client.generate(
        system_prompt=_PROMPT_PATH.read_text(encoding="utf-8"),
        user_prompt=build_insight_prompt(
            cod_sku=cod_sku,
            precio_propuesto=precio_propuesto,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            facts=facts,
        ),
        temperature=0.3,  # algo de naturalidad en la redacción, sin inventar cifras
    )
