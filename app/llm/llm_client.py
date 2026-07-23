"""Cliente LLM unificado, conmutable por proveedor.

`LLM_PROVIDER=claude` (default) usa Anthropic; `LLM_PROVIDER=gemini` usa Google.
El resto de la app (LLM #1, LLM #2, orquestador) depende solo de esta interfaz,
así que cambiar de proveedor es una línea en `.env` — no se toca la lógica.
"""

from __future__ import annotations

import time

from app.config import settings


class LLMUnavailableError(RuntimeError):
    """El modelo no respondió tras agotar reintentos (sobrecarga temporal)."""


class LLMClient:
    def __init__(self) -> None:
        self._provider = settings.llm_provider.lower().strip()
        if self._provider == "claude":
            self._init_claude()
        elif self._provider == "gemini":
            self._init_gemini()
        else:
            raise RuntimeError(
                f"LLM_PROVIDER desconocido: '{settings.llm_provider}'. "
                "Usa 'claude' o 'gemini'."
            )

    # --- Claude / Anthropic ---------------------------------------------
    def _init_claude(self) -> None:
        import anthropic

        key = settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "Falta ANTHROPIC_API_KEY en .env (formato sk-ant-api03-...)."
            )
        self._anthropic = anthropic
        # El SDK ya reintenta 429/5xx con backoff (max_retries).
        self._client = anthropic.Anthropic(api_key=key, max_retries=settings.llm_max_retries)
        self._model = settings.anthropic_model

    def _generate_claude(self, system: str, user: str, temperature: float) -> str:
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=settings.llm_max_tokens,
                system=system,
                temperature=temperature,
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.RateLimitError as e:
            raise LLMUnavailableError(
                "Claude está saturado (429). Reintenta en unos minutos."
            ) from e
        except self._anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise LLMUnavailableError(
                    f"Claude no disponible (HTTP {e.status_code})."
                ) from e
            raise
        except self._anthropic.APIConnectionError as e:
            raise LLMUnavailableError("No se pudo conectar con Claude.") from e
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    # --- Gemini / Google ------------------------------------------------
    def _init_gemini(self) -> None:
        from google import genai

        key = settings.gemini_api_key
        if not key:
            raise RuntimeError("Falta GEMINI_API_KEY en .env.")
        self._genai = genai
        self._client = genai.Client(api_key=key)
        self._model = settings.llm_model_sql

    def _generate_gemini(self, system: str, user: str, temperature: float, json: bool) -> str:
        from google.genai import errors as genai_errors
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=settings.llm_max_tokens,
            response_mime_type="application/json" if json else None,
        )
        retryable = {429, 500, 502, 503, 504}
        for attempt in range(settings.llm_max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=user, config=config
                )
                return (resp.text or "").strip()
            except genai_errors.APIError as e:
                if e.code not in retryable or attempt == settings.llm_max_retries:
                    if e.code in retryable:
                        raise LLMUnavailableError(
                            f"Gemini saturado (HTTP {e.code}). Reintenta luego."
                        ) from e
                    raise
                time.sleep(settings.llm_retry_base_delay * (2 ** attempt))
        raise LLMUnavailableError("Gemini no respondió tras varios intentos.")

    # --- API pública ----------------------------------------------------
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        json: bool = False,
    ) -> str:
        """Genera texto. `json=True` pide salida JSON (el prompt ya debe pedirla)."""
        if self._provider == "claude":
            return self._generate_claude(system_prompt, user_prompt, temperature)
        return self._generate_gemini(system_prompt, user_prompt, temperature, json)
