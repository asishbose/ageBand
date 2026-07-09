# AgeBand on the AMD Dev Cloud AI Notebook (Phase 1)

Run AgeBand on a real **MI300X** from the hosted JupyterLab
(`radeon-global.anruicloud.com`) — **no Kubernetes/Helm**, just processes + AgeBand's
env-var contract. This is Target 3 of the deploy plan; EKS (Fireworks) and the AMD SSH-VM
(k3s + Helm) are the other two targets and reuse the *same* contract.

## Why no Helm here
A hosted JupyterLab is an **unprivileged container**: no Kubernetes API, and you can't stand
up k3s (needs root + systemd + containerd). Helm therefore has nothing to talk to. So on the
notebook we run vLLM + the agent as **processes**, wired by the same env vars
(`LOCAL_API_BASE` / `EXTRACTOR_MODEL` / `ESTIMATOR_MODEL` / `AGEBAND_INFERENCE_MODE` …) that
the Helm `values-*.yaml` files set on the cluster targets. **Same code, same contract, only
the endpoint changes.**

> If the "notebook" instance is actually a root VM with JupyterLab on top, the probe (cell ①)
> shows `root + systemd` — then you *can* run k3s+Helm and it collapses into the AMD-VM target.

## The env contract (the one thing that swaps per cloud)
| Var | Notebook / AMD-VM (vLLM) | EKS (Fireworks) |
|---|---|---|
| `LOCAL_API_BASE` | `http://localhost:8000/v1` | `https://api.fireworks.ai/inference/v1` |
| `LOCAL_API_KEY` | `EMPTY` | `$FIREWORKS_API_KEY` |
| `EXTRACTOR_MODEL` / `ESTIMATOR_MODEL` | served Gemma id(s) | Fireworks model ids |
| `AGEBAND_INFERENCE_MODE` | `llm` | `llm` |
| `SKIP_AMD_CHECK` | `false` (badge on) | `true` |
| `VLLM_METRICS_URL` | `http://localhost:8000/metrics` | *(unset)* |
| `GUIDED_DECODING_ENABLED` | `1` | *(unset)* |

## How to run
1. Open the JupyterLab instance (paste your token). Upload/clone this repo so
   `deploy/notebook_bootstrap.ipynb` is available (or the notebook clones it for you).
2. Open **`notebook_bootstrap.ipynb`** and run cells top-to-bottom:
   - ① probe → ② config (edit models) → ③ source+deps → ④ **serve vLLM** (first load = minutes)
   - ⑤ env contract → ⑥ smoke test → ⑦ **adversarial demo** → ⑧ **accuracy eval** →
     ⑨ **roster benchmark** (fills the slide-9 MI300X numbers) → ⑨b telemetry badge.
3. Prefer a shell? Use the **Terminal** launcher and follow `deploy/notebook_run.sh`.

## Outputs that matter for the submission
- **⑦ adversarial**: band stays child/teen/unknown + protective posture despite adult claims
  → the "deterministic shell is load-bearing" story, now on AMD hardware.
- **⑧ eval**: confusion matrix + per-band F1 from the real MI300X model.
- **⑨ benchmark**: `slide_9_headline` = sessions/GPU · p95 ms · tok/s · $/1k turns →
  paste into `docs/benchmarks_mi300x.md` (closes PROGRESS.md task #2).
  Set `GPU_HOURLY_COST` to the real MI300X rate first.

## Rebuilding the notebook
The `.ipynb` is generated from `deploy/_build_notebook.py` (keeps cell source readable and
guarantees valid nbformat):
```
python deploy/_build_notebook.py
```

## Know your GPU (it may not be an MI300X)
The `radeon-global.anruicloud.com` instances have shipped as **Radeon PRO W7900 (`gfx1100`,
48 GB)** — *not* an Instinct MI300X (`gfx942`, 192 GB). Cell ① auto-detects this (device nodes
+ `torch` arch/VRAM) and sets `HW_LABEL` accordingly. Two consequences:
- **Model must fit 48 GB.** Default `SERVE_MODEL=google/gemma-3-4b-it` (~9 GB) fits. A bf16 27B
  (~54 GB) will **OOM**. For the larger reasoning estimator, set **`USE_QUANTIZED_LARGE=1`** →
  serves `Qwen/Qwen2.5-32B-Instruct-AWQ` (4-bit, ~20 GB) with `--quantization awq`. If AWQ
  kernels misbehave on `gfx1100`, fall back to `Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4`
  (`awq`→`gptq`) or the 4B — the pipeline is model-agnostic.
- **Benchmark labeling.** Cell ⑨ tags results with `HW_LABEL`. If it's a W7900, either relabel
  `docs/benchmarks_mi300x.md` or run the benchmark on a real MI300X for the official slide-9 numbers.

## Gotchas
- vLLM/torch are **preinstalled** on the AMD ROCm image — the notebook installs only the
  lightweight app deps; it does not touch torch/vllm.
- Background processes (vLLM, agent) are tracked in `_PROCS`; keep the kernel alive. Logs:
  `vllm.log`, `agent.log`. Run the **Cleanup** cell to stop them.
- Reaching a port in a browser needs `jupyter-server-proxy`: `…/proxy/8080/health`
  (swap `/lab` → `/proxy/8080/`). The in-process demo + eval/benchmark cells need no browser.
- The corporate-proxy TLS/CA issue is **local-machine only** — it does not affect the AMD box.
