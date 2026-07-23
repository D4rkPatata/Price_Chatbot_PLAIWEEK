"""API FastAPI del asesor de precios.

Flujo del endpoint POST /advise:
  1. Pydantic valida el input (precio > 0, fechas coherentes).
  2. Se comprueba que el SKU exista (connector) -> 404 si no.
  3. `advise()` corre el flujo LLM #1 -> DuckDB -> LLM #2.
  4. Se devuelve el insight + trazabilidad.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.config import PROJECT_ROOT
from app.data_access.sqlite_connector import get_connector
from app.llm.llm_client import LLMClient, LLMUnavailableError
from app.models.schemas import (
    GeneratedQueryOut,
    PriceAdviceRequest,
    PriceAdviceResponse,
)
from app.security.sql_guard import UnsafeSQLError
from app.services.advisor import advise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cliente LLM único (reutilizable entre requests).
    app.state.llm = LLMClient()
    yield


app = FastAPI(
    title="Chat Price Advisor",
    description="Asesor de precios: aconseja sobre un cambio de precio, no lo ejecuta.",
    version="0.1.0",
    lifespan=lifespan,
)


_WEB_DIR = PROJECT_ROOT / "web"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/skus")
def list_skus() -> list[dict]:
    """Lista de SKUs para el selector del frontend (con precio propio reciente)."""
    connector = get_connector()
    try:
        return connector.run_select(
            """
            SELECT s.COD_SKU AS cod_sku,
                   s.DESC_SKU AS desc_sku,
                   ROUND(AVG(p.precio_propio), 2) AS precio_actual
            FROM sku s
            LEFT JOIN precios p ON s.COD_SKU = p.COD_SKU
            GROUP BY s.COD_SKU, s.DESC_SKU
            ORDER BY s.DESC_SKU
            """
        )
    finally:
        connector.close()


@app.post("/advise", response_model=PriceAdviceResponse)
def advise_endpoint(req: PriceAdviceRequest) -> PriceAdviceResponse:
    connector = get_connector()
    try:
        if not connector.sku_exists(req.cod_sku):
            raise HTTPException(status_code=404, detail=f"SKU '{req.cod_sku}' no existe.")

        try:
            result = advise(
                cod_sku=req.cod_sku,
                precio_propuesto=req.precio_propuesto,
                fecha_inicio=req.fecha_inicio.isoformat(),
                fecha_fin=req.fecha_fin.isoformat(),
                connector=connector,
                llm=app.state.llm,
            )
        except UnsafeSQLError as e:
            # El LLM #1 no produjo SQL válido/seguro.
            raise HTTPException(status_code=502, detail=f"Generación de SQL inválida: {e}")
        except LLMUnavailableError as e:
            # Modelo sobrecargado (503 "high demand") tras agotar reintentos.
            raise HTTPException(status_code=503, detail=str(e))

        return PriceAdviceResponse(
            cod_sku=req.cod_sku,
            precio_propuesto=req.precio_propuesto,
            fecha_inicio=req.fecha_inicio,
            fecha_fin=req.fecha_fin,
            insight=result.insight,
            queries=[
                GeneratedQueryOut(nombre=q.nombre, objetivo=q.objetivo, sql=q.sql)
                for q in result.queries
            ],
            facts=result.facts,
            errors=result.errors,
        )
    finally:
        connector.close()
