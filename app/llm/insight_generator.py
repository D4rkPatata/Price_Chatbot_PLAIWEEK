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
    """Serializa tipos que el motor devuelve y json no maneja de fábrica."""
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def _compact_facts(facts: dict[str, list[dict[str, Any]]]) -> dict:
    """Reduce tokens: redondea floats a 2 decimales (6805563.290000014 -> 6805563.29)."""
    def r(v: Any) -> Any:
        return round(v, 2) if isinstance(v, float) else v

    return {
        nombre: [{k: r(v) for k, v in row.items()} for row in rows]
        for nombre, rows in facts.items()
    }


def _business_rules_block() -> str:
    return (
        "REGLAS DE NEGOCIO:\n"
        f"- IGV: {settings.igv} (referencial)\n"
        f"- u3m_dias: {settings.u3m_dias} (días de la ventana U3M para venta diaria promedio)"
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
    # JSON compacto (sin indentación) + floats redondeados = menos tokens.
    facts_json = json.dumps(
        _compact_facts(facts), ensure_ascii=False, separators=(",", ":"), default=_json_default
    )
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
