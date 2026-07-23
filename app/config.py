"""Configuración central del proyecto.

Todo lo que dependa del entorno (paths, umbrales de negocio, modelo LLM) vive
aquí, para que el resto del código no tenga rutas ni constantes hardcodeadas.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del repo: <root>/app/config.py -> parents[1] == <root>
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Settings de la aplicación (override vía variables de entorno o .env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Rutas de datos ---------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    duckdb_path: Path = PROJECT_ROOT / "data" / "pricing.duckdb"
    sqlite_path: Path = PROJECT_ROOT / "data" / "pricing.sqlite"

    # Nombre de archivo de cada CSV (para poder cambiarlos sin tocar código)
    precios_csv: str = "precios.csv"
    sku_csv: str = "sku.csv"
    venta_csv: str = "venta.csv"

    # --- Seguridad de queries --------------------------------------------
    # LIMIT máximo que se fuerza sobre cualquier query generada por el LLM.
    max_query_rows: int = 500
    query_timeout_s: float = 15.0

    # --- Reglas de negocio (las consume el LLM #2) -----------------------
    # Margen mínimo aceptable sobre el precio de venta (fracción, no %).
    margen_minimo: float = 0.15
    # Margen "saludable" por debajo del cual se advierte (warning suave).
    margen_objetivo: float = 0.25
    # Umbral de paridad: cuánto por encima/debajo de competencia se tolera.
    paridad_tolerancia: float = 0.05  # ±5%

    # --- LLM: proveedor -------------------------------------------------
    # "claude" (Anthropic) o "gemini" (Google). Conmutable por .env.
    llm_provider: str = "claude"

    # --- LLM: Anthropic / Claude ----------------------------------------
    anthropic_api_key: str = ""
    # Haiku 4.5: el modelo más barato de Claude ($1/$5 por 1M tokens).
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # --- LLM: Google Gemini (fallback gratuito) -------------------------
    gemini_api_key: str = ""
    # gemini-3.5-flash: buen balance calidad/velocidad/free-tier.
    llm_model_sql: str = "gemini-3.5-flash"
    llm_model_insight: str = "gemini-3.5-flash"

    # --- LLM: comunes ---------------------------------------------------
    llm_max_tokens: int = 8192
    # Reintentos ante 503/429 (sobrecarga temporal del modelo) con backoff.
    llm_max_retries: int = 4
    llm_retry_base_delay: float = 1.5  # segundos; crece exponencialmente

    @property
    def precios_path(self) -> Path:
        return self.data_dir / self.precios_csv

    @property
    def sku_path(self) -> Path:
        return self.data_dir / self.sku_csv

    @property
    def venta_path(self) -> Path:
        return self.data_dir / self.venta_csv


settings = Settings()
