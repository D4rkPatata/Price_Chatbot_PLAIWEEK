"""Modelos Pydantic del input/output del asesor de precios.

La validación aquí cubre lo que se puede verificar SIN tocar la base:
  - precio_propuesto > 0
  - fecha_fin >= fecha_inicio
  - COD_SKU no vacío (se normaliza a texto)

La existencia del SKU se valida en el endpoint (necesita el connector) para
devolver un 404 claro en vez de un 422 de validación.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class PriceAdviceRequest(BaseModel):
    cod_sku: str = Field(..., description="Código de SKU (COD_SKU).", examples=["20118348"])
    precio_propuesto: float = Field(..., gt=0, description="Nuevo precio propuesto (> 0).")
    fecha_inicio: dt.date = Field(..., description="Inicio de la vigencia (YYYY-MM-DD).")
    fecha_fin: dt.date = Field(..., description="Fin de la vigencia (YYYY-MM-DD).")

    @field_validator("cod_sku", mode="before")
    @classmethod
    def _coerce_sku(cls, v: Any) -> str:
        # Acepta int o str; normaliza a texto sin espacios (COD_SKU es VARCHAR).
        s = str(v).strip()
        if not s:
            raise ValueError("cod_sku no puede estar vacío.")
        return s

    @model_validator(mode="after")
    def _fechas_coherentes(self) -> "PriceAdviceRequest":
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin no puede ser anterior a fecha_inicio.")
        return self


class GeneratedQueryOut(BaseModel):
    nombre: str
    objetivo: str
    sql: str


class PriceAdviceResponse(BaseModel):
    cod_sku: str
    precio_propuesto: float
    fecha_inicio: dt.date
    fecha_fin: dt.date
    insight: str
    # Trazabilidad (para auditar de dónde salió el insight).
    queries: list[GeneratedQueryOut] = Field(default_factory=list)
    facts: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
