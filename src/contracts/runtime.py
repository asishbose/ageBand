"""Shared runtime-mode helper.

Decides whether AgeBand's LLM delegates (signal extraction, age-band inference)
call a real model endpoint or use the deterministic offline fallback. Read live
from the environment so tests and deployments can toggle without reimporting.
"""

from __future__ import annotations

import os


def use_llm() -> bool:
    """Return True when LLM delegates should call a real model endpoint.

    **LLM-primary framing (Phase 0):** when a model endpoint is configured,
    the LLM path is the primary perception path — it runs a reasoning-rich
    in-language pass on AMD MI300X. The deterministic path is the
    explicit offline safety-net and fallback, not a co-equal alternative.

    Controlled by ``AGEBAND_INFERENCE_MODE``:
        - ``deterministic`` → always use the deterministic offline fallback
        - ``llm``           → always use the LLM path (fail if no model is set)
        - ``auto`` (default)→ LLM when any model endpoint is configured
                              (LOCAL_MODEL or EXTRACTOR_MODEL or ESTIMATOR_MODEL),
                              else deterministic fallback

    The deterministic fallback keeps the pipeline runnable without a GPU —
    that reproducibility guarantee is unchanged; only the framing changed:
    LLM is now the **assumed default** when a model is present, with
    deterministic as the explicit, safety-net offline mode.

    **Invariant unchanged:** regardless of which path runs, the LLM NEVER
    sets a weight, confidence, or safety_posture — Python decides those.
    This function changes which path is *primary*, not who *decides*.
    """
    mode = os.environ.get("AGEBAND_INFERENCE_MODE", "auto").strip().lower()
    if mode == "deterministic":
        return False
    if mode == "llm":
        return True
    # "auto": LLM-primary — use LLM when ANY model endpoint is configured.
    return bool(
        os.environ.get("LOCAL_MODEL", "").strip()
        or os.environ.get("EXTRACTOR_MODEL", "").strip()
        or os.environ.get("ESTIMATOR_MODEL", "").strip()
    )
