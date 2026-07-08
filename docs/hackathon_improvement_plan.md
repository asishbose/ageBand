# AgeBand — AMD Hackathon Improvement Plan (Unicorn Track)

> Working plan for maximizing AgeBand's score on the AMD Developer Hackathon ACT II,
> Track 3 ("Unicorn Track"). Companion to the pitch deck
> (`Presentations` folder: `AgeBand_AMD_Pitch_v2.pptx`) and to
> [`model_comparison.md`](model_comparison.md).

---

## 1. What we are being judged on

Track 3 scores on: **creativity, originality, completeness, use of AMD platforms,
and product/market potential** — "startup pitch, not benchmark run." Separate
prize: **Best AMD-Hosted Gemma Project ($2,000)**. Submissions must be
containerized (we already ship Docker + Helm).

**Honest gap analysis (as of this plan):**

| Judging axis | Where we stand | Gap |
|---|---|---|
| Creativity / originality | Strong — passive, ephemeral, band-based inference; "model estimates, Python decides" | None major |
| Completeness | Strong in repo (86% coverage, e2e adversarial suite, eval harness) | Was invisible in the deck — now surfaced on slide 15 |
| **Use of AMD platforms** | **Weakest axis.** Integration is "any OpenAI-compatible endpoint" + a reachability check | AMD must become *load-bearing*, with evidence |
| Product/market potential | Good narrative (regulatory tailwinds, config flip) | Needs a unit-economics number |

**The unifying thesis of every item below:** the deck argues *why* self-hosting is
necessary; the winning submission *demonstrates that it runs, fast, on AMD, with
numbers*.

---

## 2. The five ideas most likely to win it (priority order)

### P0-A · Roster replay throughput benchmark on MI300X  ⭐ highest ROI

The single demo that scores three judging axes at once (AMD use, completeness,
product/market).

- Deploy on AMD Developer Cloud (MI300X, 192 GB HBM3), vLLM ROCm build.
- Replay a large DiscordChatExporter export (hundreds–thousands of authors)
  through `/v1/roster` — one session per author — against the live endpoint.
- Capture: **sessions/GPU, tokens/sec sustained, p95 gate→posture latency,
  and cost per 1,000 moderated turns vs hosted-API pricing.**
- These numbers fill the bracketed placeholders on **deck slide 9**
  (`[N] sessions/GPU · p95 [ms] · [tok/s] · $[ ]/1k turns`).
- Why it wins: AgeBand's economics *are* its pitch — "always-on for every turn of
  every user" only works if a single GPU carries a whole community. This converts
  AMD hardware directly into the startup story.

**Work items**
- [ ] `scripts/benchmark_roster.py` — drive `/v1/roster` with concurrency sweep,
      emit JSON report (reuse eval-report format in `scripts/eval_results/`).
- [ ] Scrape vLLM `/metrics` during the run (prompt/gen tokens, running seqs).
- [ ] One-page results table in `docs/benchmarks_mi300x.md`; numbers into slide 9.

### P0-B · Dual-model serving: both delegates co-located on ONE MI300X

Our most AMD-specific engineering claim — 192 GB HBM3 makes it trivial to hold a
small extractor *and* a large estimator on a single card.

- **Gemma 3 4B → M2 signal extraction** (high volume, cheap).
- **Gemma 3 27B → M4 age-band estimation** (nuance/abstention; per
  `model_comparison.md`, the bigger model wins on `ambiguous_adult`).
- Repo change is small: per-delegate model config
  (`EXTRACTOR_MODEL` / `ESTIMATOR_MODEL`, falling back to `LOCAL_MODEL`), one
  vLLM instance serving both (or two vLLM processes on one GPU).
- **Note:** the deck (slides 9 & 15) now asserts this — it must actually be wired
  before submission, or the slide 9 wording softened.

**Work items**
- [ ] Split model selection per delegate in the inference client config.
- [ ] `docs/modules/` note + `.env.example` entries.
- [ ] `make run` / Helm values support for two model names.

### P0-C · Gemma as the headline model family (prize alignment)

Gemma is already in our comparison table; making it the named pair (4B + 27B)
costs nothing and adds eligibility for the **$2,000 Best AMD-Hosted Gemma**
award. Deck naming pass is done (slides 5, 9, 10, 11, 16). Keep "any open-weight
model" as the flexibility footnote. Fireworks AI (AMD-hosted) stays the managed
fallback path — both routes remain on-message.

**Work items**
- [ ] Re-run `scripts/compare_backends.py` with Gemma 3 4B and 27B; refresh the
      table in `model_comparison.md`.
- [ ] Default `LOCAL_MODEL` examples in README/Helm to Gemma.

### P1-D · Surface AMD in the running product (telemetry badge)

Judges watch a 2–3 minute video; AMD must be visible **on screen**, not in prose.

- Upgrade `src/orchestration/amd_check.py` from reachability probe →
  evidence collector: query vLLM `/metrics` + `amd-smi` / `rocm-smi` on the
  serving box; return GPU model, ROCm version, VRAM, live tok/s via `/health`.
- UI footer badge: **"Gemma 3 27B · AMD Instinct MI300X · ROCm 6.x · N tok/s"**
  plus a small live-throughput panel next to the roster table.

**Work items**
- [ ] `amd_check.py`: add `collect_amd_telemetry()` (graceful degrade when no GPU).
- [ ] Extend `/health` response schema; UI badge component; wire to roster view.

### P1-E · The empirical proof point, front and center

`model_comparison.md`'s adversarial finding — a 31B model alone was fooled into
"adult @ 0.86" while the deterministic evasion guard held — is the strongest
evidence for the design thesis. Now on deck slide 12 (Conversation D). Make sure
the demo video *shows* it: run the adversarial transcript live against the LLM
backend and let the guard visibly refuse to settle.

---

## 3. Stretch ideas (only if time remains)

### P2-F · LoRA fine-tune a small Gemma on AMD Dev Cloud
Closes our own documented weakness ("small models under-extract"). Use the
synthetic transcript generator to build a cue-extraction training set, LoRA
fine-tune Gemma 3 4B on ROCm (torchtune / axolotl), re-run `make eval-synthetic`,
show the confusion-matrix improvement. *Documented weakness → fine-tuned on
MI300X → measured fix* is the strongest possible "meaningful use of AMD"
narrative — but it is a full workstream; attempt only after P0/P1 land.

### P2-G · vLLM guided decoding (structured output) on ROCm
One Gemma extraction call returned unparseable JSON and failed closed (correct
but wasteful). Enable vLLM `guided_json` / structured output for the M2/M4
delegates to eliminate that failure class. Small config change, shows real depth
on the AMD serving stack.

### P2-H · One-command Dev Cloud deploy
Compose file or Helm values profile that stands up vLLM-ROCm + agent + UI on an
AMD Dev Cloud instance in one shot; make it the README's primary quickstart and
demote offline/deterministic mode to a footnote for this audience.

---

## 4. The winning demo narrative (video storyboard)

1. **Cold open (20s):** the problem — a 12-year-old and a 40-year-old look
   identical to your AI. Slide 2 framing.
2. **Live demo (60s):** four conversations (slide 12). Climax = adversarial child:
   show the 31B-alone failure vs the deterministic guard holding. Step-up fires.
3. **Scale beat (40s):** roster replay of a whole community on the MI300X —
   risk-ranked table filling in, live tok/s badge visible, then the one number:
   **$X per 1,000 moderated turns on one AMD GPU.**
4. **Why AMD (20s):** slide 9 — sensitive attribute + private messages ⇒ must be
   on-prem; both Gemma delegates on one MI300X inside the operator boundary.
5. **Close (15s):** config flip, two markets, "on-prem on AMD — the only way
   something this sensitive is allowed to exist."

---

## 5. Deck ↔ repo consistency checklist (pre-submission)

- [ ] Slide 9 placeholders `[N] / [ms] / [tok/s] / $[ ]` replaced with measured
      numbers from P0-A (or column retitled "Built for MI300X Throughput" if no
      run happens).
- [ ] Dual-model serving (P0-B) actually wired before slides 9/15 claim it.
- [ ] Gemma backends re-benchmarked (P0-C) so slide 12's "31B model" footnote
      matches the refreshed comparison table.
- [ ] `/health` telemetry + UI badge (P1-D) visible in the recorded demo.
- [ ] Containerized submission verified: `make docker-build-all` +
      `make helm-lint` green.

---

## 6. Suggested execution order

| Order | Item | Effort | Blocks |
|---|---|---|---|
| 1 | P0-B dual-model config split | S | slide claims |
| 2 | P0-C Gemma re-benchmark | S | slide 12 footnote |
| 3 | P0-A roster benchmark on Dev Cloud | M | slide 9 numbers, video beat 3 |
| 4 | P1-D telemetry badge | M | video beats 3–4 |
| 5 | P2-G guided decoding | S | — |
| 6 | P2-H one-command deploy | S | — |
| 7 | P2-F LoRA fine-tune | L | stretch only |

S = hours, M = half-day, L = multi-day.

---

## 7. Approved implementation plan (2026-07-07)

**Branch:** `feat/maturity-uncertainty-masking` (off `feat/discord-roster` / PR #2).
**Full detailed plan:** `~/.claude/plans/toasty-coalescing-stonebraker.md`.

**Motivation.** In the current build the LLM is a thin JSON labeler and the
deterministic path is the default — which undersells the "use of AMD platforms"
story and leaves four requested capabilities unbuilt. This plan reframes the
architecture as **LLM-primary perception, deterministic shell adjudicates**: a
strong multilingual model on MI300X / vLLM does the heavy in-language,
reasoning-rich perception; the deterministic shell stays the thin, un-gameable,
auditable arbiter + offline safety-net. Core invariant untouched — **the LLM
never sets a weight or confidence; Python decides band + confidence + posture.**
The new capabilities are exactly what the English keyword lexicon *cannot* do,
so they force genuine LLM/GPU work while the shell keeps the "no confident-wrong
label" guarantee (empirically motivated: gemma4:31b was fooled by an adversarial
child; the deterministic guard held).

**Approved decisions.**

1. LLM-primary flip.
2. Multilingual via the LLM + eval harness (no per-language lexicons).
3. Maturity indicators = weak nudge + mismatch-only, never establish a band.
4. Conversation uncertainty = internal confidence penalty.
5. Masking detector generalized in both estimators.
6. AMD showcases = MI300X/vLLM multilingual + vLLM guided decoding + embeddings
   for cross-turn consistency.

**Phases (build order).**

| Phase | Scope |
|---|---|
| Prereq (done) | Fix `evidence_fabric/decay.py` dropping `Cue.subtype` |
| Phase 0 — LLM-primary flip | `runtime.py` docs + `primary_backend()`; `llm_client` bounded retry |
| Phase 1 — Multilingual + eval | `language_detect.py`; LLM language hint; deterministic path abstains (→ `unknown`) on non-English; `scripts/eval_multilang.py` + labeled fixtures (es/hi/fr/ar/zh) |
| Phase 2 — Maturity scorers/cues | `maturity.py` (linguistic + interaction); weak `_SPECIAL_META` subtypes (weight 0.3); `cue_type_for_any` guard keeps them out of `_STRONG_TYPES` |
| Phase 3 — Conversation uncertainty | `EvidenceSummary.band_history`; `_compute_uncertainty` penalty in `confidence.py` (conflicting leans / volatility / maturity-mismatch / sparsity). Must be 0 for existing fixtures |
| Phase 4 — Masking detector | Generalize evasion to 4 patterns (mismatch, deflection, register-switching, over-insistence) in `rule_estimator` + LLM prompt; strict superset of today's rule |
| Phase 5 — AMD showcases | vLLM guided decoding (confidence-free schema) + embeddings persona consistency (neutral no-op offline) |

**Cross-references to sections 2–3.** Phase 5's guided decoding subsumes P2-G.
Phase 1 (multilingual on MI300X) directly addresses the cross-language weak spot
named on deck slide 13 and strengthens the P0 "use of AMD" story: the LLM-primary
flip makes the GPU the default perception path rather than an optional backend.
P0-A (roster benchmark), P0-B (dual-model split), and P1-D (telemetry badge)
remain independent and should be sequenced around these phases per §6.
