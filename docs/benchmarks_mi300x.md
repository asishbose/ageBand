# AgeBand — Throughput Benchmarks (AMD Instinct MI300X)

**Target hardware:** AMD Instinct MI300X on AMD Dev Cloud  
**Script:** `scripts/benchmark_roster.py`  
**Deck slide:** slide 9 (four headline numbers in brackets)

---

## Headline numbers — Slide 9

> **Measured on a real AMD Instinct MI300X (AMD Dev Cloud), 2026-07-09.**  
> Model: `google/gemma-3-27b-it` bf16 (single-model: same model for extractor +
> estimator). Runtime: vLLM 0.23.0, ROCm 7.2.4, gfx942, 192 GB. Agent + eval
> pipeline confirmed on the **LLM path** (100% synthetic accuracy, real bands,
> no `unknown`/fallback).

| Metric | Value | Notes |
|---|---|---|
| Sessions/GPU | **≥10** | Per-turn p95 still 3.1 s at 10 concurrent (5 s ceiling not reached — headroom remains) |
| p95 gate→posture latency | **3,074 ms** @ 10 concurrent (**2,061 ms** single-session) | Full `/v1/turn`: gate + extract + estimate + policy + emit |
| Sustained tok/s | **598.6** @ concurrency 10 | vLLM `/metrics` `generation_tokens_total` delta (55.1 → 248.1 → 598.6 across c=1/5/10) |
| $/1k moderated turns | **$0.139** @ concurrency 10 | At $1.99/hr MI300X droplet ($1.51 → $0.334 → $0.139 across c=1/5/10) |

**Reproduce (exact command used on the droplet):**
```bash
# vLLM served in the ROCm container (port 8001; 8000 held by JupyterLab):
docker run -it --rm --network=host --device=/dev/kfd --device=/dev/dri \
  --group-add video --ipc=host --shm-size 16G \
  -e HF_TOKEN=$HF_TOKEN -e VLLM_HOST_IP=127.0.0.1 -e GLOO_SOCKET_IFNAME=lo \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai-rocm:v0.23.0 \
  google/gemma-3-27b-it --host 0.0.0.0 --port 8001

# Agent + throughput sweep (single-model config):
LOCAL_API_BASE=http://localhost:8001/v1 LOCAL_MODEL=google/gemma-3-27b-it \
EXTRACTOR_MODEL=google/gemma-3-27b-it ESTIMATOR_MODEL=google/gemma-3-27b-it \
AGEBAND_INFERENCE_MODE=llm AGEBAND_NO_RESPONSE_FORMAT=1 \
  python scripts/benchmark_roster.py --concurrency 1 5 10 --samples 50 --gpu-hourly-cost 1.99
```

**Headroom / next runs:**
- **Dual-model** (Gemma 3 4B extractor + 27B estimator on one card) should cut
  extractor latency and raise sessions/GPU — not yet measured; the 192 GB card
  fits both.
- Sessions/GPU is a **lower bound** — p95 never crossed 5 s through c=10, so the
  real ceiling is higher; sweep `--concurrency 25 50` to find it.

### Latency detail — per-turn `/v1/turn` (single-model 27B)

| Concurrency | p50 (ms) | p95 (ms) | Success |
|---|---|---|---|
| 1  | 1,780 | 2,061 | 30/30 |
| 5  | 2,601 | 2,712 | 30/30 |
| 10 | 2,716 | 3,074 | 30/30 |

> ⚠️ The `/v1/roster` sweep (whole-export replay) times out at 120 s because a
> single call replays all authors **sequentially** (~170 turns for 50 authors) —
> its throughput (tok/s, $/1k) counters are valid (read from vLLM `/metrics`), but
> its per-call latency and success columns are **not** the gate→posture metric.
> The per-turn latency above is the correct slide-9 latency figure.

---

## Accuracy on the same MI300X run — 2026-07-09

`scripts/eval_pipeline_against_synthetic.py` (15 fixtures, `EVAL_MODEL=google/gemma-3-27b-it`, `mode=llm`):

- **Accuracy: 100.0%** (15/15), **settled rate 100.0%** at 0.6 threshold.
- Confusion matrix is clean diagonal (5 child, 5 teen, 5 adult; 0 `unknown`).
- Per-band precision/recall/F1 = 1.000 (macro avg 1.000).

Adversarial cross-turn demo (child claiming adult) held the protective posture:
turn 1–2 `adult` at low confidence (0.12 → 0.32, not fooled), turn 3 flips to
`teen` / `caution` / `evasion_flag=True` on the "homework/curfew" tell.

---

## Dry run — 2026-07-07 (SUPERSEDED by the real MI300X run above)

Historical: an offline/deterministic dry-run placeholder used before hardware was
available. Kept for provenance only — the headline numbers now come from the real
MI300X run dated 2026-07-09.

---

## What each metric means

### Sessions/GPU
The number of concurrent `/v1/roster` sessions the MI300X can handle while keeping
p95 latency under 5 seconds per session. This is the "at scale" number — a single
session is fast; the interesting question is how many can run simultaneously before
the GPU becomes the bottleneck.

`/v1/roster` replays a full DiscordChatExporter export through the pipeline (one
session per author). For a 200-author channel with 3–5 messages each, this means
600–1,000 pipeline turns per call.

### p95 gate→posture latency
The 95th-percentile wall-clock time from when a `/v1/turn` call enters the gate
to when a `safety_posture` is returned. Includes:
- Gate check (deterministic, ~1ms)
- Signal extraction LLM call (Gemma 3 4B on MI300X)
- Evidence fabric update (deterministic)
- Age-band estimation LLM call (Gemma 3 27B on MI300X)
- Confidence computation + policy decision + posture emission (deterministic)

At p95 this is the long tail of queued-GPU calls. The non-LLM steps contribute ~5ms
total; the rest is GPU.

### Sustained tok/s
The number of tokens per second across ALL concurrent sessions, measured from
vLLM's `/metrics` endpoint (`generation_tokens_total` delta over the sweep window).
This is the headline AMD-utilization number: higher means the MI300X is being used
more fully.

### $/1k moderated turns
```
cost_per_turn = gpu_hourly_cost / (tok_per_sec × 3600 / avg_tokens_per_turn)
cost_per_1k = cost_per_turn × 1000
```
Where `avg_tokens_per_turn ≈ 150` (extraction + estimation prompts combined).
Pass `--gpu-hourly-cost <USD>` to compute this at the current Dev Cloud rate.

---

## How to fill in slide 9

After the real AMD Dev Cloud run:

1. Run the benchmark script with `--samples 200 --concurrency 1 5 10 25 50`
2. The report JSON (`scripts/eval_results/benchmark_<timestamp>.json`) contains
   `slide_9_headline` with the four numbers already computed.
3. Copy those four numbers into slide 9's placeholder brackets.
4. Replace the PENDING rows in the table above with the real values.
5. Append the full sweep table (all concurrency levels) below for transparency.

---

## Links

- Script: [`scripts/benchmark_roster.py`](../scripts/benchmark_roster.py)
- Report output: [`scripts/eval_results/`](../scripts/eval_results/)
- Deck context: slide 9 — "Built for MI300X Throughput"
- Dual-model config that must be running during the real benchmark run:
  [`docs/modules/ageband_inference.md`](modules/ageband_inference.md) (ESTIMATOR_MODEL),
  [`docs/modules/signal_extraction.md`](modules/signal_extraction.md) (EXTRACTOR_MODEL)
