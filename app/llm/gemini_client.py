"""Cliente delgado sobre el SDK de Google Gemini (google-genai).

Un único punto de acceso al LLM para todo el proyecto. Los dos "agentes"
(SQL y insight) usan este mismo cliente con distinto system prompt y,
opcionalmente, distinto modelo.
"""

from __future__ import annotations

import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import settings

# Códigos que valen la pena reintentar: sobrecarga/temporal, no errores del input.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMUnavailableError(RuntimeError):
    """El modelo no respondió tras agotar los reintentos (sobrecarga temporal)."""


class GeminiClient:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.gemini_api_key
        if not key:
            raise RuntimeError(
                "Falta GEMINI_API_KEY. Cópiala en .env (ver .env.example)."
            )
        self._client = genai.Client(api_key=key)

    def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_mime_type: str | None = None,
    ) -> str:
        """Llama al modelo y devuelve el texto de la respuesta.

        Reintenta con backoff exponencial ante 429/5xx (sobrecarga temporal
        del modelo, como el 503 "high demand"). Los errores de input (4xx) no
        se reintentan. `response_mime_type="application/json"` fuerza JSON.
        """
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=settings.llm_max_tokens,
            response_mime_type=response_mime_type,
        )

        last_exc: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=model, contents=user_prompt, config=config
                )
                return (resp.text or "").strip()
            except genai_errors.APIError as e:
                if e.code not in _RETRYABLE_STATUS or attempt == settings.llm_max_retries:
                    if e.code in _RETRYABLE_STATUS:
                        raise LLMUnavailableError(
                            f"El modelo '{model}' está sobrecargado (HTTP {e.code}). "
                            "Reintenta en unos minutos."
                        ) from e
                    raise
                last_exc = e
                time.sleep(settings.llm_retry_base_delay * (2 ** attempt))

        # No debería llegar aquí, pero por completitud.
        raise LLMUnavailableError(str(last_exc))
