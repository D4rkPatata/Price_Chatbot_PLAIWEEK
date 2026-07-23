# Chat Price Advisor

Backend de un chatbot **asesor de precios**. El usuario propone un cambio de
precio para un SKU (SKU + precio propuesto + vigencia) y el bot devuelve
**insights y razonamiento** sobre qué podría pasar. **No ejecuta el cambio.**

Corre 100% local simulando el entorno GCP: la data está en CSV, un LLM genera
el SQL, y se ejecuta con **DuckDB** (sintaxis compatible BigQuery). El día que
haya permisos de BigQuery, solo cambia el *connector* de datos.

## Estructura del proyecto

```
26. Chat_Price_PLAIWEEK/
├─ data/                       # CSV fuente + pricing.duckdb (generado)
│  ├─ precios.csv             # precio propio + competencia + venta reciente (~1 mes)
│  ├─ sku.csv                 # maestro: F_PRECIO_COSTO + ELASTICIDAD + jerarquía
│  └─ venta.csv               # historia de ventas ~1 año (estacionalidad)
├─ app/
│  ├─ config.py               # settings: paths, umbrales de negocio, LLM
│  ├─ models/
│  │  └─ schemas.py           # (punto 3) Pydantic input/output
│  ├─ data_access/
│  │  ├─ connector.py         # interfaz abstracta DataConnector (local ↔ BigQuery)
│  │  ├─ duckdb_connector.py  # (punto 2) DuckDB sobre CSV, vía vistas
│  │  └─ schema_catalog.py    # descripción de tablas (para el LLM #1)
│  ├─ security/
│  │  └─ sql_guard.py         # solo SELECT + LIMIT forzado, sin DDL/DML
│  ├─ llm/
│  │  ├─ sql_generator.py     # (punto 4) LLM #1: pregunta -> SQL
│  │  ├─ insight_generator.py # (punto 5) LLM #2: resultado -> insight NL
│  │  └─ prompts/             # prompts en texto plano
│  ├─ services/
│  │  └─ advisor.py           # (orquesta el flujo completo)
│  └─ main.py                 # (punto 6) FastAPI + endpoint
├─ scripts/
│  └─ build_duckdb.py         # (punto 2) crea/valida la base DuckDB
├─ tests/                      # (punto 7) tests con data dummy
├─ .env.example
├─ pyproject.toml
└─ README.md
```

## Las 3 tablas y qué insight alimentan

| Tabla     | Filas  | Rango           | Alimenta                                       |
|-----------|--------|-----------------|------------------------------------------------|
| `precios` | 2.730  | ~1 mes reciente | Paridad competencia, precio base, contexto     |
| `sku`     | 93     | maestro         | Margen (F_PRECIO_COSTO), impacto (ELASTICIDAD) |
| `ventas`  | 33.559 | ~1 año          | Estacionalidad / timing                        |

Join: `precios.COD_SKU = sku.COD_SKU = ventas.cod_sku`

## Setup

```bash
uv sync                                   # instala dependencias
cp .env.example .env                      # y completa ANTHROPIC_API_KEY

# Inicializa / valida la base DuckDB
uv run python -m scripts.build_duckdb --check   # smoke-test en memoria
uv run python -m scripts.build_duckdb           # crea data/pricing.duckdb (vistas)
uv run python -m scripts.build_duckdb --materialize  # tablas físicas (opcional)
```

## Estado

- [x] 1. Estructura de carpetas
- [x] 2. Setup DuckDB (`build_duckdb.py` + connector con vistas sobre CSV)
- [x] 3. Modelo Pydantic del input (`models/schemas.py`)
- [x] 4. Prompt LLM #1 (genera SQL seguro) — Claude `claude-haiku-4-5` (o Gemini vía `LLM_PROVIDER`)
- [x] 5. Prompt LLM #2 (genera insight) + orquestador `services/advisor.py`
- [x] 6. Endpoint FastAPI (`app/main.py` → POST /advise)
- [ ] 7. Tests con data dummy

## Correr la API + frontend

```bash
uv run uvicorn app.main:app --reload
```

- **Frontend:** http://127.0.0.1:8000/  (selector de SKU + precio + vigencia)
- **Swagger UI:** http://127.0.0.1:8000/docs
- **Endpoints:** `GET /` (web) · `GET /skus` · `POST /advise` · `GET /health`

Ejemplo de request:

```bash
curl -X POST http://127.0.0.1:8000/advise -H "Content-Type: application/json" -d '{
  "cod_sku": "20118348",
  "precio_propuesto": 11.9,
  "fecha_inicio": "2026-08-01",
  "fecha_fin": "2026-08-31"
}'
```
