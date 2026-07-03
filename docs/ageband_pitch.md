# AgeBand

### A passive age-band signal from the conversation that gets more protective the more it suspects a child — and asks before it assumes. On-prem, because this is far too sensitive to run anywhere else.

---

**Track:** Unicorn · **Domain:** Trust &amp; Safety for AI chat products · **Runs on:** Self-hosted open-weight LLM on AMD GPUs

---

## The one-liner

AgeBand reads how a user writes and what they talk about, maintains a live estimate of their **age band** (child / teen / adult / unknown) with a **confidence**, and drives graduated safety — quietly tightening protections the more it suspects a minor, and asking to confirm before it acts on a strong guess. No cameras, no biometrics, no profile.

## The problem

Every AI chat product is under pressure to protect minors, and the tool they have is a birthdate field at signup that any kid clicks through. After that, the product treats a 12-year-old and a 40-year-old identically.

The signal it's ignoring is right there: **how people write and what they talk about.** A trust-and-safety expert can read a transcript and know roughly who they're talking to in seconds — but that judgement isn't automated, always-on, or scalable to millions of conversations.

## The solution

A passive, always-on signal that runs inside the product:

1. **Extract** age-relevant cues from each message — vocabulary, topics (school, guardians, homework), explicit statements, style.
2. **Accumulate** evidence across the conversation — it starts at *unknown* and only moves as cues corroborate, so one ambiguous line won't swing it.
3. **Estimate** a band + confidence, with the signals cited — explainable, not a black box, and free to say *unknown*.
4. **Decide** with a deterministic, tunable policy — the model estimates, the policy emits a `safety_posture`. Low confidence tightens filters a little; higher confidence escalates proportionally.
5. **Step up, don't slam the door** — a high-impact protection asks the user to confirm age rather than acting silently on a guess. Explicit confirmation always overrides.

## Why it's credible where "age detection" isn't

The naive version — "detect the user's age and block them" — fails on accuracy, bias, and privacy. AgeBand is designed around those failures: **bands not precise ages** (text can't reliably tell 16 from 18, so it doesn't pretend to); **graduated responses not hard blocks**; **ask-don't-assume at the boundary**; **ephemeral signal not a profile.** That's the difference between a compliance liability and a feature a platform can ship.

## Why it needs AMD

Inferring "is this a minor" from private messages is the most sensitive attribute computed from the most sensitive data a product holds. It legally and ethically cannot go to a third-party API — it has to run inside the product's own boundary, on its own hardware. Self-hosting isn't a compute story here; it's the entire reason this can exist. And always-on inference over every conversation is a real throughput load.

## Why it wins

Every AI chat product needs this and none of them have it — they're stuck with an ignored birthdate field. AgeBand is the missing passive, privacy-preserving safety signal, and its responsible design (bands, confidence, graduated, ask-first, ephemeral) is exactly what lets a platform actually deploy it. **Same pipeline flips for a kids' product detecting adults — only the policy table changes.**

## The demo

Four conversations side by side. The adult stays open. The young-teen one watches confidence climb as school and guardian references stack up — safety tightening step by step until it asks to confirm age. The ambiguous one (an adult who writes simply) is the fairness money shot: confidence *stays low*, so AgeBand tightens only slightly and **asks** rather than locking anyone out. And the adversarial one — a child claiming to be an adult — is the crux: AgeBand reads the evasion itself as a weak signal, keeps confidence off "adult," and routes to a step-up instead of being fooled.

> *"It doesn't guess your age and slam a door. It gets more careful the more it suspects a child, and it asks before it assumes."*

## Build

Open-weight LLM (Llama/Qwen-class) on AMD via ROCm or Fireworks · signal extractor + session-scoped evidence store · deterministic policy table (band × confidence → `safety_posture`) · a planner-supervisor that routes each turn (agentic, but the safety steps stay deterministic and fail closed) · a live UI showing band, confidence, evidence, and the active posture.
