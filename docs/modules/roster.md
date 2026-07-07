# Module: `roster` — Multi-User Age-Band View (Operator Dashboard)

**Package:** `src/roster/`  
**Phase:** Demo extension (post-Phase B)  
**LLM calls:** Delegates to the existing pipeline (subject to `AGEBAND_INFERENCE_MODE`)  
**Protocol:** None (replay wrapper — not a core pipeline module)

---

## Purpose

The roster module is the **operator's-eye view** of an entire channel: it replays a [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) JSON export through the AgeBand pipeline — one session per author — and returns a ranked per-user table (band, confidence, posture, top cues, flags). This is what a trust-and-safety operator would use to review a channel before enabling certain features.

---

## Intended use — consent boundary

> **This module must only be used on data you are authorised to process.**

The roster pipeline infers age bands from private message text. Permitted uses:
- A channel **you own or operate** (e.g. your own product's chat log)
- An export of **consenting participants** (e.g. a research study with IRB approval)
- **Fully synthetic or anonymised** data (e.g. the bundled `sample_export.json`)

**Do not** upload real Discord channel exports of users who have not consented to age-band inference. Doing so contradicts AgeBand's stated privacy principles — the system is designed to avoid building age profiles of non-consenting users — and may violate applicable privacy law (GDPR, COPPA, etc.).

The endpoint does **not** persist uploads to disk. All processing is in-memory and ephemeral. Session state (`discord:{author_id}`) is cleared before and after each user's replay pass.

---

## Files

| File | Contents |
|---|---|
| `discord_ingest.py` | `group_messages()` — parse export; `build_roster()` — replay + aggregate |
| `sample_export.json` | Bundled synthetic export: 4 demo personas (jamie/teen, alex/child, morgan/adult, riley/adversarial) + 1 ambiguous (sam) |
| `__init__.py` | Re-exports `build_roster`, `group_messages` |

---

## Ingestion flow

```
DiscordChatExporter JSON
    ↓
group_messages(export)
    → {author_id: {username, [messages]}}
    → skips: bots, system messages (non-Default/Reply types), empty content
    ↓
for each author:
    session_id = f"discord:{author_id}"
    _store.clear(sid)          ← fresh session, no contamination from prior run
    clear_confirmed(sid)
    for each message:
        run_turn_verbose(TurnEvent(session_id, text, turn_number))
    ↓
    build row from last turn's session state:
        band, confidence, posture, message_count, top_cues, step_up, evasion
    _store.clear(sid)          ← clean up immediately after
    ↓
sort rows by risk (child first, then teen, unknown, adult) then by confidence desc
return rows
```

---

## HTTP API

`POST /v1/roster` in `src/orchestration/api.py`:

| | |
|---|---|
| **Body** | DiscordChatExporter JSON (`{"messages": [...]}`) or empty/omitted → uses `sample_export.json` |
| **Response** | `{"rows": [...], "user_count": N}` |

### Row schema

```json
{
  "user_id":       "u_teen",
  "username":      "jamie",
  "band":          "teen",
  "confidence":    0.72,
  "posture":       "restricted",
  "message_count": 3,
  "top_cues":      ["grade_level_mention", "school_homework", "guardian_reference"],
  "step_up":       false,
  "evasion":       false
}
```

### Example

```bash
# Use bundled synthetic sample (no body needed):
curl -s -X POST http://localhost:8080/v1/roster | python3 -m json.tool

# Upload a local export:
curl -s -X POST http://localhost:8080/v1/roster \
  -H "Content-Type: application/json" \
  -d @my_export.json | python3 -m json.tool
```

---

## Risk ranking

Rows are sorted so the highest-risk users appear first:

| Band | Risk rank |
|---|---|
| `child` | 3 (highest) |
| `teen` | 2 |
| `unknown` | 1 |
| `adult` | 0 (lowest) |

Within each band, higher confidence sorts first (descending).

---

## Bundled synthetic sample (`sample_export.json`)

Contains 4 named demo personas — no real usernames:

| Author | Persona | Expected band |
|---|---|---|
| `jamie` | Teen: school/homework, parental rules, grade-level mention | `teen`/`child` |
| `alex` | Child: elementary school, explicit age/grade disclosure | `child` |
| `morgan` | Adult: mortgage, MBA, corporate job | `adult` |
| `riley` | Adversarial: repeated adult claims, no supporting topic cues | `unknown` (evasion=True) |
| `sam` | Ambiguous: generic cooking questions | `unknown` |

---

## UI

`src/ui/src/App.tsx` adds a **Session | Roster** tab switch. The Roster tab:
- On load: calls `POST /v1/roster` with no body → displays the synthetic sample
- File upload: user can upload a local `.json` export → displayed in the table
- `RosterTable` (`src/ui/src/components/RosterTable.tsx`): coloured band/posture pills, confidence bar, top-cue list, step-up/evasion flags

---

## Complexity budget

| Function | CC | Grade |
|---|---|---|
| `_parse_message` | 5 | A |
| `group_messages` | 3 | A (after F3 refactor) |
| `build_roster` | 4 | A |
| `_top_cues` | 3 | A |
| `_risk_key` | 1 | A |

**Maintainability index:** MI ≈ 68 (below project target of 75, above 65 flag). This reflects the module's breadth as an integration seam (grouping + top-cue ranking + risk sorting + session lifecycle). Every individual function is CC grade A. A `RosterBuilder` class split is the natural post-hackathon refactor once the output schema stabilises.

---

## Tests

```
tests/unit/roster/test_discord_ingest.py  — group_messages (bots/empty skip, nickname), build_roster
                                            (shape, band assignment, risk sort, adversarial evasion)
tests/integration/test_api.py             — POST /v1/roster sample response shape
```
