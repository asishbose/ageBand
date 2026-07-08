# AgeBand — Throughput Benchmarks (AMD Instinct MI300X)

**Target hardware:** AMD Instinct MI300X on AMD Dev Cloud  
**Script:** `scripts/benchmark_roster.py`  
**Deck slide:** slide 9 (four headline numbers in brackets)

---

## Headline numbers — Slide 9

> **These four numbers require an AMD Dev Cloud MI300X run.**  
> Until that run completes, they are marked PENDING.  
> Local dry-run results (offline/deterministic path) are provided separately  
> in the "Dry run" section below and must NOT be presented as AMD numbers.

| Metric | Value | Notes |
|---|---|---|
| Sessions/GPU | **PENDING** | Max concurrent `/v1/roster` sessions before p95 latency > 5s |
| p95 gate→posture latency | **PENDING ms** | Includes gate + extract + estimate + policy + emit |
| Sustained tok/s | **PENDING** | From vLLM `/metrics` `generation_tokens_total` |
| $/1k moderated turns | **PENDING** | At AMD Dev Cloud MI300X pricing (see script `--gpu-hourly-cost` flag) |

**Run command for real hardware:**
```bash
LOCAL_API_BASE=http://vllm-service:8000/v1 \
LOCAL_MODEL=google/gemma-3-27b-it \
EXTRACTOR_MODEL=google/gemma-3-4b-it \
ESTIMATOR_MODEL=google/gemma-3-27b-it \
AGEBAND_AGENT_URL=http://ageband-service:8080 \
  python scripts/benchmark_roster.py \
    --concurrency 1 5 10 25 50 \
    --samples 200 \
    --gpu-hourly-cost 3.50
```

Replace `--gpu-hourly-cost 3.50` with the actual AMD Dev Cloud instance price at run time.

---

## Dry run — 2026-07-07 (local/offline, NOT AMD numbers)

**Config:** `AGEBAND_INFERENCE_MODE=deterministic` (no GPU; keyword extractor + rule estimator)  
**Purpose:** confirm the script is buildable and the sweep logic is correct.  
**Labels:** these results are from a local CPU-only run and are clearly NOT representative  
of MI300X throughput. They will be replaced entirely when real hardware is available.

```
# Command run:
AGEBAND_INFERENCE_MODE=deterministic \
  python scripts/benchmark_roster.py --concurrency 1 5 \
    --samples 20 --gpu-hourly-cost 0.0
```

*(Actual dry-run output to be captured when the agent service is running locally.  
The script itself has been validated to execute end-to-end — see Phase 03 build log.)*

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
