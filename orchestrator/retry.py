from __future__ import annotations

import random
import time


class TransientError(Exception):
    """Falla recuperable (timeout, servicio intermitente)."""


class PermanentError(Exception):
    """Falla que no tiene sentido reintentar (dato inválido, no encontrado)."""


def backoff_delay(attempt: int, base: float = 0.2) -> float:
    """Backoff exponencial corto con jitter. attempt es 1-based."""
    if attempt <= 1:
        return 0.0
    delay = base * (2 ** (attempt - 2))
    jitter = random.uniform(-0.2, 0.2)
    return max(0.0, delay * (1 + jitter))


def should_retry(error: Exception) -> bool:
    return isinstance(error, TransientError)


def run_with_retry(fn, *, max_attempts: int = 3, sleep_fn=time.sleep):
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(), attempt
        except Exception as exc:
            last_error = exc
            if not should_retry(exc) or attempt >= max_attempts:
                raise
            sleep_fn(backoff_delay(attempt + 1))
    raise last_error  # pragma: no cover
