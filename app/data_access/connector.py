"""Interfaz abstracta del connector de datos.

El resto de la app (servicios, LLM #2) depende SOLO de esta interfaz, nunca
de DuckDB directamente. El día que existan permisos de BigQuery se agrega un
`BigQueryConnector(DataConnector)` y se cambia una línea en la fábrica; la
lógica del agente no se toca.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataConnector(ABC):
    """Contrato mínimo que debe cumplir cualquier backend de datos."""

    @abstractmethod
    def run_select(self, sql: str) -> list[dict[str, Any]]:
        """Ejecuta un SELECT de solo lectura y devuelve filas como dicts.

        La implementación es responsable de aplicar los límites de seguridad
        (solo lectura, LIMIT, timeout). El SQL ya debe venir validado por
        `app.security.sql_guard`, pero el connector es la última barrera.
        """
        raise NotImplementedError

    @abstractmethod
    def sku_exists(self, cod_sku: str) -> bool:
        """True si el SKU existe en la tabla maestra. Usado en validación."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
