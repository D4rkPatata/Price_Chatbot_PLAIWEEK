"""Catálogo lógico de tablas.

Fuente única de verdad de: qué tablas existen, qué columnas tienen, qué
significan y cómo se relacionan. Lo consumen dos cosas:

  1. El connector (DuckDB hoy, BigQuery mañana) para registrar las tablas
     con estos MISMOS nombres lógicos.
  2. El prompt del LLM #1, que necesita el schema para generar SQL correcto.

Al mantener los nombres lógicos aquí, migrar de CSV local a BigQuery solo
implica cambiar el connector: el LLM sigue viendo `precios`, `sku`, `ventas`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str
    description: str


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    grain: str  # granularidad: qué representa una fila
    columns: list[Column] = field(default_factory=list)


# Clave de join entre las tres tablas.
JOIN_KEY = "COD_SKU"

PRECIOS = Table(
    name="precios",
    description=(
        "Precios diarios recientes por SKU (~1 mes). Es la única tabla con "
        "precio propio, precio de competencia y desempeño diario reciente."
    ),
    grain="una fila por SKU y día (fecha)",
    columns=[
        Column("COD_SKU", "TEXT", "Código de SKU. Join con sku y ventas."),
        Column("DESC_SKU", "TEXT", "Descripción del producto."),
        Column("DESC_SUBDEPARTAMENTO", "TEXT", "Subdepartamento (para comparar pares)."),
        Column("fecha", "TEXT", "Fecha del registro de precio/venta."),
        Column("precio_propio", "REAL", "Precio propio vigente ese día."),
        Column("precio_competencia", "REAL", "Precio de competencia observado ese día."),
        Column("unidades_totales", "REAL", "Unidades vendidas ese día."),
        Column("venta_total", "REAL", "Venta (monto) ese día."),
    ],
)

SKU = Table(
    name="sku",
    description=(
        "Tabla maestra de SKU. Única fuente de costo y elasticidad. "
        "Una fila por SKU."
    ),
    grain="una fila por SKU",
    columns=[
        Column("COD_SKU", "TEXT", "Código de SKU. Join con precios y ventas."),
        Column("COD_SKU_COMPARABLE", "TEXT", "Código del SKU espejo (marca opuesta) para paridad MMPP/MMCC. Join a sku para traer su precio y FLG_MMPP."),
        Column("DESC_SKU", "TEXT", "Descripción del producto."),
        Column("DESC_SUBDEPARTAMENTO", "TEXT", "Subdepartamento."),
        Column("FAMILIA", "TEXT", "Familia del producto (agrupador)."),
        Column("FLG_MMPP", "TEXT", "1 = marca propia (MMPP); 0 = marca comercial (MMCC)."),
        Column("F_PRECIO_COSTO", "REAL", "Costo unitario (sin impuestos)."),
        Column(
            "ELASTICIDAD",
            "REAL",
            "Elasticidad precio-demanda (magnitud). % cambio de demanda por "
            "1% de cambio de precio. Mayor valor = más sensible al precio.",
        ),
    ],
)

VENTAS = Table(
    name="ventas",
    description=(
        "Historia larga de ventas diarias (~1 año). NO tiene precio unitario, "
        "pero sí montos y costo. Fuente para: GPE real, volumen U3M (últimos 3 "
        "meses), estacionalidad mensual y participación por día de la semana."
    ),
    grain="una fila por SKU y día (ID_DIAVENTA)",
    columns=[
        Column("ID_DIAVENTA", "TEXT", "Fecha de la venta (ISO 'YYYY-MM-DD')."),
        Column("COD_SKU", "TEXT", "Código de SKU. Join con precios y sku."),
        Column("VTA_SI", "REAL", "Venta del día SIN impuestos. Usar para el GPE real."),
        Column("UNIDADES", "REAL", "Unidades vendidas del día."),
        Column("COSTO_VENTA", "REAL", "Costo de la venta del día. Usar para el GPE real."),
    ],
)

ALL_TABLES: list[Table] = [PRECIOS, SKU, VENTAS]


def render_schema_for_prompt() -> str:
    """Devuelve el schema en texto plano, listo para inyectar en el prompt del LLM #1."""
    lines: list[str] = []
    for t in ALL_TABLES:
        lines.append(f"TABLE {t.name}  -- {t.description}")
        lines.append(f"  (grano: {t.grain})")
        for c in t.columns:
            lines.append(f"    {c.name} {c.dtype}  -- {c.description}")
        lines.append("")
    lines.append("JOIN: precios.COD_SKU = sku.COD_SKU = ventas.COD_SKU")
    return "\n".join(lines)
