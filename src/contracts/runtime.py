"""Shared runtime-mode helper.

Decides whether AgeBand's LLM delegates (signal extraction, age-band inference)
call a real model endpoint or use the deterministic offline fallback. Read live
from the environment so tests and deployments can toggle without reimporting.
"""

from __future__ import annotations

import os


def use_llm() -> bool:
    """Return True when LLM delegates should call a real model endpoint.

    Controlled by ``AGEBAND_INFERENCE_MODE``:
        - ``deterministic`` → always use the offline fallback
        - ``llm``           → always use the LLM path
        - ``auto`` (default)→ use the LLM only when ``LOCAL_MODEL`` is configured

    The offline fallback keeps the whole pipeline runnable without a GPU or a
    model server, which is what makes the demo reproducible.
    """
    mode = os.environ.get("AGEBAND_INFERENCE_MODE", "auto").strip().lower()
    if mode == "deterministic":
        return False
    if mode == "llm":
        return True
    return bool(os.environ.get("LOCAL_MODEL", "").strip())
