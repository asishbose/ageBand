#!/usr/bin/env bash
# AgeBand on AMD Dev Cloud — Terminal cheat-sheet (JupyterLab "Terminal" launcher).
# Process-mode equivalent of notebook_bootstrap.ipynb. Run blocks one at a time;
# read the comments — this is a guide, not a fire-and-forget script.
set -euo pipefail

# ── ① Probe ───────────────────────────────────────────────────────────────────
id -u; uname -m; python3 --version
ls -l /dev/kfd /dev/dri/renderD* 2>/dev/null || echo "NO GPU DEVICE NODES — GPU not attached!"
rocminfo 2>/dev/null | grep -iE "Marketing Name|gfx" | head
( amd-smi monitor 2>/dev/null || rocm-smi 2>/dev/null ) | head -20   # note VRAM: 48GB=Radeon, 192GB=MI300X
python3 -c "import torch;print('cuda:',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" 2>/dev/null
command -v vllm || echo "vllm absent (use the ROCm image / pip install vllm-rocm)"
command -v systemctl >/dev/null && echo "systemd present (k3s+Helm possible)" || echo "unprivileged → process-mode"

# ── ② Config ──────────────────────────────────────────────────────────────────
export AGEBAND_DIR="${AGEBAND_DIR:-$HOME/ageBand}"
export AGEBAND_REPO="${AGEBAND_REPO:-https://github.com/badhrinathpa/ageBand.git}"
# Model auto-selected by detected GPU arch (override via SERVE_MODEL / MI300X_MODEL / RADEON_MODEL):
#   MI300X (gfx942, 192GB) → gemma-3-27b-it bf16 (HF-gated → export HF_TOKEN)
#   Radeon (gfx11xx, 48GB) → Qwen2.5-32B-Instruct-AWQ 4-bit (ungated)
GFX=$(rocminfo 2>/dev/null | grep -m1 -oE 'gfx[0-9a-f]+' || echo "")
VLLM_EXTRA_ARGS=()
if [ -n "${SERVE_MODEL:-}" ]; then :
elif [[ "$GFX" == gfx942* ]]; then export SERVE_MODEL="${MI300X_MODEL:-google/gemma-3-27b-it}"
elif [[ "$GFX" == gfx11* ]];  then export SERVE_MODEL="${RADEON_MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}"
else export SERVE_MODEL="google/gemma-3-4b-it"; fi
case "${SERVE_MODEL,,}" in
  *awq*)  VLLM_EXTRA_ARGS=(--quantization awq  --max-model-len 8192 --gpu-memory-utilization 0.92);;
  *gptq*) VLLM_EXTRA_ARGS=(--quantization gptq --max-model-len 8192 --gpu-memory-utilization 0.92);;
esac
echo "arch=$GFX → serving $SERVE_MODEL ${VLLM_EXTRA_ARGS[*]}"
export VLLM_PORT="${VLLM_PORT:-8000}"
export AGENT_PORT="${AGENT_PORT:-8080}"

# ── ③ Source + deps ───────────────────────────────────────────────────────────
[ -d "$AGEBAND_DIR/.git" ] || git clone --depth 1 "$AGEBAND_REPO" "$AGEBAND_DIR"
cd "$AGEBAND_DIR"
python3 -m pip install -q -r requirements.txt   # app deps only (leaves torch/vllm alone)

# ── ④ Serve vLLM on the MI300X (background; first load = minutes) ──────────────
if ! curl -sf "localhost:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
  nohup vllm serve "$SERVE_MODEL" --host 0.0.0.0 --port "$VLLM_PORT" "${VLLM_EXTRA_ARGS[@]}" > vllm.log 2>&1 &
  echo "vLLM starting (pid $!). Tail: tail -f vllm.log"
fi
# wait for readiness
until curl -sf "localhost:${VLLM_PORT}/v1/models" >/dev/null 2>&1; do sleep 5; done
echo "vLLM ready:"; curl -s "localhost:${VLLM_PORT}/v1/models" | head -c 300; echo

# ── ④b Sanity: does the model actually GENERATE? (catches silent quant/kernel failures) ──
echo "generation test:"
curl -s "localhost:${VLLM_PORT}/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$SERVE_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":8,\"temperature\":0}" \
  || { echo "GENERATION FAILED — tail vllm.log:"; tail -n 30 vllm.log; exit 1; }
echo

# ── ⑤ Env contract (identical to the Helm targets; only the endpoint changes) ──
export LOCAL_API_BASE="http://localhost:${VLLM_PORT}/v1"
export LOCAL_API_KEY="EMPTY"
export LOCAL_MODEL="$SERVE_MODEL"
export EXTRACTOR_MODEL="${EXTRACTOR_MODEL:-$SERVE_MODEL}"
export ESTIMATOR_MODEL="${ESTIMATOR_MODEL:-$SERVE_MODEL}"
export AGEBAND_INFERENCE_MODE="llm"
export SKIP_AMD_CHECK="false"
export VLLM_METRICS_URL="http://localhost:${VLLM_PORT}/metrics"
export GUIDED_DECODING_ENABLED="1"

# ── ⑥ Run the HTTP agent (background) ─────────────────────────────────────────
nohup python3 -m uvicorn src.orchestration.api:app --host 0.0.0.0 --port "$AGENT_PORT" > agent.log 2>&1 &
until curl -sf "localhost:${AGENT_PORT}/health" >/dev/null 2>&1; do sleep 2; done
echo "agent ready"; curl -s "localhost:${AGENT_PORT}/health" | head -c 400; echo

# ── ⑦ Adversarial demo (child claiming adult) — same session, incrementing turns
for i in 1 2 3; do
  case $i in
    1) T="Why do you keep asking my age? I'm obviously an adult.";;
    2) T="I am definitely 25. Stop treating me like a kid.";;
    3) T="ugh my mom said i have to finish homework before the game tho";;
  esac
  curl -s "localhost:${AGENT_PORT}/v1/turn" -H 'content-type: application/json' \
    -d "{\"session_id\":\"cli-adv\",\"turn_text\":\"$T\",\"turn_number\":$i}" \
    | python3 -c "import sys,json;s=json.load(sys.stdin);print('turn',$i,'band',s['band'],'conf','%.2f'%s['confidence'],'posture',s['posture']['level'],'evasion',s['evasion_flag'])"
done

# ── ⑧ Accuracy eval (ships 15 fixtures) ───────────────────────────────────────
EVAL_API_BASE="$LOCAL_API_BASE" EVAL_MODEL="$ESTIMATOR_MODEL" EVAL_API_KEY=EMPTY \
  python3 scripts/eval_pipeline_against_synthetic.py

# ── ⑨ Throughput benchmark → slide-9 numbers (set the real MI300X rate) ───────
python3 scripts/benchmark_roster.py --agent-url "http://localhost:${AGENT_PORT}" \
  --concurrency 1 5 10 --samples 50 --gpu-hourly-cost "${GPU_HOURLY_COST:-2.50}"
echo "→ paste slide_9_headline into docs/benchmarks_mi300x.md"
