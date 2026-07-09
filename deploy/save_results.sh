#!/usr/bin/env bash
# Save AgeBand run outputs OFF the ephemeral GPU droplet before you destroy it.
# (AMD bills even when powered off — only destroy stops charges, and destroy wipes the disk.)
#
# It: (1) bundles eval + benchmark JSON into a downloadable tarball under deploy/,
#     (2) prints the slide-9 headline numbers, and
#     (3) pushes results to your fork IF GITHUB_TOKEN is set (else tells you to download).
#
# Usage (from the repo root, after your run):
#     bash deploy/save_results.sh
#     # to also push to the fork:
#     export GITHUB_TOKEN=ghp_xxx && bash deploy/save_results.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1          # repo root

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="deploy/results_${TS}"
mkdir -p "$OUT"

# 1. Collect result JSONs (benchmark_*, multilang_*, eval report *.json)
cp scripts/eval_results/*.json "$OUT"/ 2>/dev/null \
  && echo "copied $(ls "$OUT"/*.json 2>/dev/null | wc -l | tr -d ' ') result file(s)" \
  || echo "(no scripts/eval_results/*.json found — did the eval/benchmark cells run?)"

# 2. Self-documenting run metadata (so numbers are traceable to hardware/model)
{
  echo "timestamp:   $TS"
  echo "host:        $(hostname)"
  echo "gpu_arch:    $(rocminfo 2>/dev/null | grep -m1 -oE 'gfx[0-9a-f]+' || echo unknown)"
  echo "vllm:        $(vllm --version 2>/dev/null | head -1 || echo n/a)"
  echo "serve_model: ${SERVE_MODEL:-unset}"
  echo "env:         MODE=${AGEBAND_INFERENCE_MODE:-} NO_RESPONSE_FORMAT=${AGEBAND_NO_RESPONSE_FORMAT:-} GUIDED=${GUIDED_DECODING_ENABLED:-}"
} | tee "$OUT/run_metadata.txt"

# 3. Print the slide-9 headline from the newest benchmark JSON
BENCH=$(ls -t scripts/eval_results/benchmark_*.json 2>/dev/null | head -1)
if [ -n "$BENCH" ]; then
  echo; echo "=== slide-9 headline ($BENCH) ==="
  python3 -c "import json;print(json.dumps(json.load(open('$BENCH')).get('slide_9_headline',{}),indent=2))" 2>/dev/null \
    || echo "(couldn't parse slide_9_headline)"
fi

# 4. Tarball for one-click download via the JupyterLab file browser
tar czf "${OUT}.tgz" -C deploy "results_${TS}" 2>/dev/null \
  && echo && echo "Bundle: ${OUT}.tgz  ← right-click → Download in the JupyterLab file browser"

# 5. Optional push to the fork (needs a GitHub PAT; HTTPS password auth is disabled by GitHub)
if [ -n "${GITHUB_TOKEN:-}" ]; then
  BR=$(git rev-parse --abbrev-ref HEAD)
  git add -f "$OUT" "${OUT}.tgz" 2>/dev/null
  git -c user.email=ageband@local -c user.name=ageband commit -q -m "MI300X run results $TS" \
    && URL=$(git remote get-url origin | sed "s#https://#https://x-access-token:${GITHUB_TOKEN}@#") \
    && git push "$URL" "HEAD:$BR" && echo "pushed results to origin/$BR" \
    || echo "commit/push skipped or failed — use the tarball (${OUT}.tgz) instead"
else
  echo
  echo "GITHUB_TOKEN not set → skipped git push. Get results off the box by either:"
  echo "  • downloading ${OUT}.tgz via the JupyterLab file browser, or"
  echo "  • export GITHUB_TOKEN=ghp_xxx && bash deploy/save_results.sh   (to push to the fork)"
fi

echo
echo "Saved. You can now DESTROY the droplet — remember: powered-off still bills; only destroy stops it."
