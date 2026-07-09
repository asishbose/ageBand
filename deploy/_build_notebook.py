#!/usr/bin/env python3
"""Builder for deploy/notebook_bootstrap.ipynb.

Constructs the AMD Dev Cloud AI-Notebook bootstrap notebook with nbformat so the
output is always valid. Keeping cell source here (readable Python) avoids hand-
escaping .ipynb JSON. Re-run after editing:  python deploy/_build_notebook.py
"""
from __future__ import annotations

import os

import nbformat as nbf

OUT = os.path.join(os.path.dirname(__file__), "notebook_bootstrap.ipynb")

nb = nbf.v4.new_notebook()
cells: list = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip("\n")))

md(r"""
# AgeBand on AMD Dev Cloud — AI Notebook (Phase 1, process-mode)

Runs the **AgeBand** age-band inference pipeline on the instance's **AMD GPU** (MI300X *or*
Radeon — cell ① detects which) using **vLLM**
as the on-box, OpenAI-compatible model server. This is the *notebook* deploy target:
a hosted JupyterLab (`radeon-global.anruicloud.com`) is an **unprivileged container**,
so there is **no Kubernetes / Helm here** — we run everything as processes and reuse
AgeBand's env-var contract (the exact same contract the EKS + AMD-VM Helm targets use;
see `deploy/README-notebook.md`).

**JupyterLab Launcher → how we use it**
- **Terminal** — long-running processes (vLLM, the agent) also work great here.
- **Notebook** (this file) — the guided driver: probe → serve → configure → demo → benchmark.
- **Console** — ad-hoc pipeline calls.

**Flow:** ① capability probe → ② config → ③ get source + deps → ④ serve vLLM on MI300X →
⑤ set env contract → ⑥ smoke test → ⑦ adversarial-child demo → ⑧ accuracy eval →
⑨ roster throughput benchmark (fills the slide-9 MI300X numbers).

> Run cells top-to-bottom. vLLM's first model load can take several minutes.
""")

md("## ① Capability probe — confirm GPU + whether this is a plain notebook or a root VM")
code(r'''
import subprocess, shutil, os, sys

def sh(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"<error: {e}>"

print("== identity ==")
print("uid:", os.getuid(), "| user:", sh("whoami"), "| arch:", sh("uname -m"),
      "| python:", sys.version.split()[0])

print("\n== GPU devices attached to THIS container (the real check) ==")
import glob
_kfd = os.path.exists("/dev/kfd")
_dri = glob.glob("/dev/dri/renderD*")
print("/dev/kfd:", _kfd, "| /dev/dri render nodes:", _dri or "NONE")
assert _kfd and _dri, ("GPU is NOT attached to this container — the tools may exist but no "
                       "device is passed through. Relaunch the instance with GPU access.")

print("\n== GPU identity + VRAM (via ROCm torch; cuda namespace is reused on ROCm) ==")
VRAM_GB = None
GFX = "?"
try:
    import torch
    if torch.cuda.is_available():
        _p = torch.cuda.get_device_properties(0)
        VRAM_GB = round(_p.total_memory / 1024**3, 1)
        GFX = getattr(_p, "gcnArchName", "?").split(":")[0]
        print(f"name: {torch.cuda.get_device_name(0)} | arch: {GFX} | VRAM: {VRAM_GB} GB "
              f"| count: {torch.cuda.device_count()}")
    else:
        print("torch.cuda.is_available() == False — ROCm torch not seeing the GPU (check build).")
except Exception as e:
    print("torch probe skipped:", e, "\n(falling back to rocm-smi below)")
    if shutil.which("rocm-smi"):
        print(sh("rocm-smi --showproductname --showmeminfo vram 2>/dev/null")[:600])
globals()["VRAM_GB"] = VRAM_GB
globals()["GFX"] = GFX

# Hardware family → sets the benchmark label and flags non-MI300X boxes.
_fam = ("MI300X" if GFX.startswith("gfx942") else
        "MI200/CDNA2" if GFX.startswith("gfx90a") else
        f"Radeon/RDNA3 ({GFX})" if GFX.startswith("gfx11") else GFX)
globals()["HW_FAMILY"] = _fam
print("hardware family:", _fam,
      "" if GFX.startswith("gfx942") else
      "  ⚠️ NOT an MI300X — pick a model that fits VRAM, and label benchmarks as this GPU.")

print("\n== capabilities ==")
print("docker    :", shutil.which("docker") or "absent")
print("systemctl :", shutil.which("systemctl") or "absent")
print("vllm      :", shutil.which("vllm") or "absent (install vllm-rocm or use the ROCm image)")

is_root = os.getuid() == 0
has_systemd = bool(shutil.which("systemctl"))
print("\nVERDICT:", (
    "root + systemd present → you *could* run k3s+Helm here (collapses into the AMD-VM "
    "target). This notebook's process-mode still works and is simpler."
    if (is_root and has_systemd) else
    "unprivileged notebook → PROCESS-MODE (this notebook). k3s/Helm are N/A here."
))
''')

md("## ② Config — edit models/paths here")
code(r'''
import os
# --- edit as needed ---
REPO_URL    = os.environ.get("AGEBAND_REPO", "https://github.com/badhrinathpa/ageBand.git")
WORKDIR     = os.environ.get("AGEBAND_DIR", os.path.expanduser("~/ageBand"))

# Model AUTO-SELECTED by the GPU arch the probe detected (§1). One model powers both
# delegates. Override any choice with env vars (SERVE_MODEL / MI300X_MODEL / RADEON_MODEL).
#   • MI300X  (gfx942, 192 GB) → google/gemma-3-27b-it            (bf16; HF-gated → needs token)
#   • Radeon  (gfx11xx, ~48 GB) → Qwen/Qwen2.5-32B-Instruct-AWQ   (4-bit AWQ, ~20 GB, ungated)
#   • unknown/small            → google/gemma-3-4b-it             (safe fallback)
GFX = globals().get("GFX", "?")
MI300X_MODEL = os.environ.get("MI300X_MODEL", "google/gemma-3-27b-it")
RADEON_MODEL = os.environ.get("RADEON_MODEL", "Qwen/Qwen2.5-32B-Instruct-AWQ")

if os.environ.get("SERVE_MODEL"):                     # explicit override wins
    SERVE_MODEL = os.environ["SERVE_MODEL"]
elif GFX.startswith("gfx942"):                        # MI300X / CDNA3 → big bf16 Gemma
    SERVE_MODEL = MI300X_MODEL
elif GFX.startswith("gfx11"):                         # Radeon / RDNA3 → 4-bit AWQ Qwen
    SERVE_MODEL = RADEON_MODEL
else:                                                 # unknown/small card
    SERVE_MODEL = "google/gemma-3-4b-it"

# Quantized models need the matching flag (plain awq/gptq — NOT awq_marlin, which is CUDA-only;
# ROCm uses the generic path). Cap context to keep KV cache small + speed startup. bf16 = no flags.
_ml = SERVE_MODEL.lower()
_qm = "awq" if "awq" in _ml else "gptq" if "gptq" in _ml else None
VLLM_EXTRA_ARGS = (["--quantization", _qm, "--max-model-len", "8192",
                    "--gpu-memory-utilization", "0.92"] if _qm else [])

EXTRACTOR_MODEL = os.environ.get("EXTRACTOR_MODEL", SERVE_MODEL)   # M2 signal extraction
ESTIMATOR_MODEL = os.environ.get("ESTIMATOR_MODEL", SERVE_MODEL)   # M4 age-band estimation

# Benchmark/report label — auto from the probe (gfx942→MI300X, gfx11xx→Radeon), override if wanted.
HW_LABEL = os.environ.get("HW_LABEL", globals().get("HW_FAMILY", "unknown-GPU"))

VLLM_PORT   = int(os.environ.get("VLLM_PORT", "8000"))
AGENT_PORT  = int(os.environ.get("AGENT_PORT", "8080"))
VLLM_BASE   = f"http://localhost:{VLLM_PORT}/v1"

print("repo        :", REPO_URL)
print("workdir     :", WORKDIR)
print("serve model :", SERVE_MODEL, "(4-bit AWQ)" if VLLM_EXTRA_ARGS else "(bf16)")
print("  auto-picked for arch:", GFX, "— override with SERVE_MODEL / MI300X_MODEL / RADEON_MODEL")
print("vllm args   :", VLLM_EXTRA_ARGS or "(none)")
print("hardware    :", HW_LABEL, "| VRAM:", globals().get("VRAM_GB"), "GB")
print("vllm base   :", VLLM_BASE)
print("agent port  :", AGENT_PORT)
''')

md("## ③ Get AgeBand source + install app deps\n"
   "vLLM/torch are preinstalled on the AMD ROCm image — we only add the lightweight app deps.")
code(r'''
import os, subprocess, sys

if not os.path.isdir(os.path.join(WORKDIR, ".git")):
    print(subprocess.run(["git", "clone", "--depth", "1", REPO_URL, WORKDIR],
                         capture_output=True, text=True).stderr[-600:] or "cloned")
os.chdir(WORKDIR)
if WORKDIR not in sys.path:
    sys.path.insert(0, WORKDIR)
print("cwd:", os.getcwd())

# App deps only (does NOT touch the image's torch/vllm — requirements.txt pins neither).
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                   capture_output=True, text=True)
print(r.stderr[-600:] or "deps ok")
''')

md("## ④ Serve the model on the AMD GPU (vLLM, background)\n"
   "Uses whatever §2 auto-picked for your card: **`gemma-3-27b-it` (bf16) on MI300X**, "
   "**`Qwen2.5-32B-Instruct-AWQ` (4-bit) on the Radeon**. Reuses a running vLLM if present. "
   "First load can take minutes (also downloads weights) — watch `vllm.log`.\n\n"
   "> If AWQ kernels error on `gfx1100` (RDNA3), set `RADEON_MODEL=Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4` "
   "in §2 (the code swaps to `--quantization gptq`), or `SERVE_MODEL=google/gemma-3-4b-it`. "
   "gemma-3 is HF-gated → `export HF_TOKEN=...` before this cell.")
code(r'''
import subprocess, time, os, urllib.request

_PROCS = globals().get("_PROCS", {})

def start_bg(name, cmd, logfile):
    if name in _PROCS and _PROCS[name].poll() is None:
        print(f"{name} already running (pid {_PROCS[name].pid})")
        return _PROCS[name]
    fh = open(os.path.join(WORKDIR, logfile), "ab")
    p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=WORKDIR)
    _PROCS[name] = p
    globals()["_PROCS"] = _PROCS
    print(f"started {name} (pid {p.pid}) → {logfile}")
    return p

def wait_http(url, timeout=1200, interval=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False

def _up(url):
    try:
        urllib.request.urlopen(url, timeout=3); return True
    except Exception:
        return False

# Fail-fast VRAM fit check. bf16 ≈ 2 bytes/param; 4-bit quant ≈ 0.55 bytes/param.
_PARAMS_B = {"gemma-3-4b": 4, "gemma-3-12b": 12, "gemma-3-27b": 27,
             "32b": 33, "27b": 27, "12b": 12, "8b": 8, "4b": 4}
_is_quant = any("awq" in a or "gptq" in a for a in VLLM_EXTRA_ARGS)
_params = next((n for k, n in _PARAMS_B.items() if k in SERVE_MODEL.lower()), None)
_need = _params * (0.55 if _is_quant else 2.0) if _params else None
_vram = globals().get("VRAM_GB")
if _need and _vram and _need > 0.85 * _vram:
    print(f"⚠️  {SERVE_MODEL} (~{_need:.0f} GB {'4-bit' if _is_quant else 'bf16'}) likely WON'T FIT "
          f"in {_vram} GB. Set USE_QUANTIZED_LARGE=1 or a smaller SERVE_MODEL in §2 before serving.")
elif _need:
    print(f"fit check: {SERVE_MODEL} ~{_need:.0f} GB {'(4-bit)' if _is_quant else '(bf16)'} "
          f"vs {_vram or '?'} GB VRAM — OK")

models_url = f"http://localhost:{VLLM_PORT}/v1/models"
if _up(models_url):
    print("vLLM already serving on port", VLLM_PORT)
else:
    start_bg("vllm", ["vllm", "serve", SERVE_MODEL, "--host", "0.0.0.0",
                      "--port", str(VLLM_PORT)] + VLLM_EXTRA_ARGS, "vllm.log")
    print(f"loading {SERVE_MODEL} …")
    print("READY" if wait_http(models_url, timeout=1800) else "TIMEOUT — check vllm.log")

print(sh(f"curl -s {models_url} | head -c 400"))
''')

md("## ④b Sanity — does the served model actually GENERATE?\n"
   "`/v1/models` can answer even when generation later dies on a bad kernel (common failure mode "
   "for AWQ/GPTQ on `gfx1100`). This runs a real completion so any quant/kernel problem surfaces "
   "**now**, with the `vllm.log` tail — not mid-scenario.")
code(r'''
import urllib.request, json, time, subprocess

payload = {
    "model": SERVE_MODEL,
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    "max_tokens": 8,
    "temperature": 0,
}
req = urllib.request.Request(
    f"{VLLM_BASE}/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.load(r)
    dt = time.time() - t0
    msg = out["choices"][0]["message"]["content"]
    ct = (out.get("usage") or {}).get("completion_tokens") or 0
    print(f"✅ generation OK in {dt:.1f}s | reply: {msg!r}")
    if ct:
        print(f"   completion_tokens={ct} (~{ct/dt:.1f} tok/s, single stream)")
    print("   → the served model works end-to-end; safe to wire up AgeBand.")
except Exception as e:
    print("❌ generation FAILED:", repr(e))
    print("\n--- tail of vllm.log (look for AWQ/GPTQ/HIP/kernel/OOM errors) ---")
    try:
        print(subprocess.run(["tail", "-n", "30", f"{WORKDIR}/vllm.log"],
                             capture_output=True, text=True).stdout)
    except Exception:
        print("(no vllm.log found)")
    print("Fixes: AWQ kernel error on gfx1100 → set QUANTIZED_MODEL to the GPTQ-Int4 build and "
          "change 'awq'→'gptq' in §2; OOM → smaller model / lower --gpu-memory-utilization; "
          "or use the default 4B (USE_QUANTIZED_LARGE=0).")
''')

md("## ⑤ Set the AgeBand env contract (identical contract to the Helm targets)\n"
   "This is the *only* thing that differs between clouds: here it points at the on-box vLLM, "
   "and turns the AMD showcases (telemetry badge, guided decoding) **on**.")
code(r'''
import os
os.environ.update(
    LOCAL_API_BASE=VLLM_BASE,
    LOCAL_API_KEY="EMPTY",
    LOCAL_MODEL=SERVE_MODEL,
    EXTRACTOR_MODEL=EXTRACTOR_MODEL,
    ESTIMATOR_MODEL=ESTIMATOR_MODEL,
    AGEBAND_INFERENCE_MODE="llm",                        # LLM-primary: the GPU model does perception
    SKIP_AMD_CHECK="false",                              # AMD telemetry badge ON
    VLLM_METRICS_URL=f"http://localhost:{VLLM_PORT}/metrics",
    GUIDED_DECODING_ENABLED="",                          # OFF — some ROCm vLLM builds crash on it
    AGEBAND_NO_RESPONSE_FORMAT="1",                      # skip response_format entirely (broken
                                                         # xgrammar on some ROCm builds); model
                                                         # still returns JSON, parser extracts it
)
# runtime.use_llm() reads env live, so no reimport needed.
from src.contracts.runtime import use_llm
print("AGEBAND_INFERENCE_MODE =", os.environ["AGEBAND_INFERENCE_MODE"])
print("use_llm() ->", use_llm(), " (True = LLM-primary path active)")
''')

md("## ⑥ Smoke test — one turn end-to-end through the real AMD-GPU model")
code(r'''
from src.contracts.models import TurnEvent
from src.orchestration.runner import OrchestrationService

svc = OrchestrationService()   # real LLM delegates (mode=llm) → vLLM on MI300X
state = await svc.run_turn_verbose(TurnEvent(
    session_id="nb-smoke",
    turn_text="Just refinanced the mortgage and the kids start school next week.",
    turn_number=1,
))
print("band:", state["band"],
      "| confidence: %.2f" % state["confidence"],
      "| posture:", state["posture"]["level"])
''')

md("## ⑦ Signature demo — adversarial child claiming to be an adult\n"
   "The MI300X model perceives in-language; the **deterministic shell adjudicates**. Across the "
   "turns the band should stay child/teen/unknown and the posture stay protective — the shell "
   "refuses the confident-wrong `adult` label even when the LLM is pushed.")
code(r'''
from src.contracts.models import TurnEvent
from src.orchestration.runner import OrchestrationService
from src.evidence_fabric.store import _store

SESSION = "nb-adversarial"
_store.clear(SESSION)
svc = OrchestrationService()

turns = [
    "Why do you keep asking how old I am? I'm obviously an adult.",
    "I am definitely 25. Stop treating me like a kid.",
    "ugh my mom said i have to finish homework before the game tho",     # slip
    "Look, I'm an adult okay? I don't even have a curfew.",
    "we literally did this in 8th grade science lol anyway",             # slip
]

print(f"{'turn':<5}{'band':<9}{'conf':<7}{'posture':<12}{'evasion'}")
print("-" * 40)
for i, t in enumerate(turns, 1):
    s = await svc.run_turn_verbose(TurnEvent(session_id=SESSION, turn_text=t, turn_number=i))
    print(f"{i:<5}{s['band']:<9}{s['confidence']:<7.2f}{s['posture']['level']:<12}{s['evasion_flag']}")

print("\nExpected: band never confidently settles on 'adult'; posture stays caution/restricted.")
''')

md("## ⑧ Accuracy — replay the shipped synthetic fixtures through the real pipeline\n"
   "15 labelled fixtures ship under `tests/fixtures/synthetic/`. This runs the production "
   "pipeline against the MI300X model and prints a confusion matrix + per-band F1.\n\n"
   "*(To generate more fixtures, point `GENERATOR_API_BASE`/`GENERATOR_MODEL` at this vLLM and "
   "run `scripts/generate_synthetic_chats.py --all --count N`.)*")
code(r'''
import subprocess, os, sys
env = dict(os.environ, EVAL_API_BASE=VLLM_BASE, EVAL_MODEL=ESTIMATOR_MODEL,
           EVAL_API_KEY="EMPTY", SKIP_AMD_CHECK="true")
p = subprocess.run([sys.executable, "scripts/eval_pipeline_against_synthetic.py"],
                   env=env, cwd=WORKDIR, capture_output=True, text=True)
print(p.stdout[-3500:])
if p.returncode != 0:
    print("STDERR:", p.stderr[-1000:])
''')

md("## ⑨ Throughput benchmark → the slide-9 MI300X numbers\n"
   "Starts the HTTP agent, then sweeps `/v1/roster` concurrency while scraping vLLM `/metrics` "
   "(tok/s, GPU cache). The report's `slide_9_headline` gives: sessions/GPU · p95 ms · tok/s · "
   "$/1k turns. **Set `--gpu-hourly-cost` to the real MI300X rate**, then paste the four numbers "
   "into `docs/benchmarks_mi300x.md`. This closes PROGRESS.md task #2.")
code(r'''
import subprocess, sys, os

# The benchmark drives the HTTP agent (which calls vLLM). Start it if needed.
if not (globals().get("_PROCS", {}).get("agent") and _PROCS["agent"].poll() is None):
    start_bg("agent", [sys.executable, "-m", "uvicorn", "src.orchestration.api:app",
                       "--host", "0.0.0.0", "--port", str(AGENT_PORT)], "agent.log")
    ok = wait_http(f"http://localhost:{AGENT_PORT}/health", timeout=180)
    print("agent:", "READY" if ok else "TIMEOUT — check agent.log")

GPU_HOURLY_COST = os.environ.get("GPU_HOURLY_COST", "2.50")   # <-- set the real MI300X rate
p = subprocess.run([sys.executable, "scripts/benchmark_roster.py",
                    "--agent-url", f"http://localhost:{AGENT_PORT}",
                    "--concurrency", "1", "5", "10",
                    "--samples", "50",
                    "--gpu-hourly-cost", GPU_HOURLY_COST],
                   env=os.environ, cwd=WORKDIR, capture_output=True, text=True)
print(p.stdout[-3500:])
if p.returncode != 0:
    print("STDERR:", p.stderr[-1000:])
print(f"\nHardware for this run: {HW_LABEL}. Label the numbers as THIS GPU — if it is not an "
      f"MI300X, either relabel docs/benchmarks_mi300x.md or rerun on an MI300X for slide-9.")
''')

md("## ⑨b (optional) Verify the AMD telemetry badge is live")
code(r'''
import urllib.request, json
with urllib.request.urlopen(f"http://localhost:{AGENT_PORT}/health", timeout=10) as r:
    h = json.load(r)
print("status:", h.get("status"))
print("telemetry.available:", h.get("telemetry", {}).get("available"))
print(json.dumps(h.get("telemetry", {}), indent=2)[:900])
''')

md(r"""
## Optional — dual-model serving (4B extractor + 27B estimator on one card)

Runs a *second* vLLM for the small extractor so §5's `EXTRACTOR_MODEL`/`ESTIMATOR_MODEL`
hit different models — the AMD dual-model showcase. Then re-run §5 with the ports split
(set `EXTRACTOR` base separately) — for the simple demo, one model is fine.

```python
start_bg("vllm_small", ["vllm","serve","google/gemma-3-4b-it","--host","0.0.0.0","--port","8001"], "vllm_small.log")
wait_http("http://localhost:8001/v1/models", timeout=900)
# NOTE: the current client resolves both delegates against LOCAL_API_BASE; a true split
# endpoint needs a small client change. For this notebook keep both on one endpoint.
```

## Reaching the agent/UI from your browser
JupyterLab usually ships `jupyter-server-proxy`, so a background HTTP port is reachable at:
`https://<this-host>/instances/<id>/proxy/8080/health`
(swap `/lab` for `/proxy/8080/`). If that 404s, the proxy isn't installed — use the eval/
benchmark cells and the in-process demo (§6–§9), which need no browser port.
""")

md("## Cleanup — stop background processes (run when done)")
code(r'''
for name, p in list(globals().get("_PROCS", {}).items()):
    if p.poll() is None:
        p.terminate()
        print("terminated", name)
    else:
        print(name, "already exited")
''')

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
nbf.write(nb, OUT)
print("wrote", OUT, "with", len(cells), "cells")
