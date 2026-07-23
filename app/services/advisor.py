"""Orquestador del flujo completo del asesor de precios.

    LLM #1 (genera SQL)  ->  DuckDB (ejecuta)  ->  LLM #2 (insight)

Es el único lugar que conoce el flujo entero. El endpoint FastAPI (punto 6)
solo llama a `advise(...)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.data_access.connector import DataConnector
from app.data_access.sqlite_connector import get_connector
from app.llm.llm_client import LLMClient
from app.llm.insight_generator import generate_insight
from app.llm.sql_generator import GeneratedQuery, generate_queries


@dataclass
class AdviceResult:
    insight: str
    queries: list[GeneratedQuery] = field(default_factory=list)
    facts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def advise(
    *,
    cod_sku: str,
    precio_propuesto: float,
    fecha_inicio: str,
    fecha_fin: str,
    connector: DataConnector | None = None,
    llm: LLMClient | None = None,
) -> AdviceResult:
    """Ejecuta el flujo end-to-end y devuelve el insight + trazabilidad."""
    connector = connector or get_connector()
    llm = llm or LLMClient()

    # 1) LLM #1: pregunta -> SQL validado
    queries = generate_queries(
        cod_sku=cod_sku,
        precio_propuesto=precio_propuesto,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        client=llm,
    )

    # 2) Ejecutar cada query en DuckDB, recolectar hechos por objetivo.
    facts: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for q in queries:
        try:
            facts[q.nombre] = connector.run_select(q.sql)
        except Exception as e:  # noqa: BLE001 - queremos degradar con gracia
            errors[q.nombre] = f"{type(e).__name__}: {e}"

    # 3) LLM #2: hechos + reglas de negocio -> insight en español
    insight = generate_insight(
        cod_sku=cod_sku,
        precio_propuesto=precio_propuesto,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        facts=facts,
        client=llm,
    )

    return AdviceResult(insight=insight, queries=queries, facts=facts, errors=errors)
