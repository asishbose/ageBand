# AgeBand — Live Demo Runbook

A step-by-step script to run the full AgeBand demo end-to-end on a fresh AMD GPU
droplet: **create → login → clone → JupyterLab → Run All → showcase the UI**.

Read it top to bottom the first time. Total time from a cold droplet: **~15 min**
(most of it the one-time ~52 GB model download). Subsequent runs: **~3 min**.

> **Legend**
> `$` = run in a terminal on your **laptop**  ·  `#` = run in the **droplet** shell
> 🗣 = what to say / show during the demo

---

## 0. Pre-flight (do this before the audience is watching)

- [ ] DigitalOcean account with **GPU droplet** access (AMD MI300X).
- [ ] A **Hugging Face token** with the Gemma license accepted:
      accept at <https://huggingface.co/google/gemma-3-27b-it>, then create a token
      at <https://huggingface.co/settings/tokens>. You'll paste it as `HF_TOKEN`.
- [ ] Your SSH key added to DigitalOcean.
- [ ] The droplet's **public IP** handy once created.

> 💡 **Best practice:** do a full dry run (steps 1–5) at least once *before* the real
> demo so the 52 GB weights are already cached. On the second run vLLM is up in
> ~2–3 min and nothing downloads.

---

## 1. Create the GPU droplet

DigitalOcean dashboard → **Create → Droplets**:

| Setting | Value |
|---|---|
| Image | Ubuntu 24.04 LTS x64 |
| Droplet type | **GPU — AMD MI300X** |
| Disk | ≥ 200 GB (weights are ~52 GB + KV cache) |
| Region | Closest to you with GPU stock |
| Authentication | **SSH key** |

Create it, then copy the **public IP** (e.g. `134.199.197.118`).

### Open the firewall ports

Only two ports need to be reachable from your browser:

| Port | Purpose |
|---|---|
| `8889` | JupyterLab |
| `8080` | AgeBand app (API + UI, one origin) |

`8001` (vLLM) stays **local-only** — the app talks to it over localhost, so don't expose it.

**DigitalOcean Cloud Firewall (recommended):** Networking → Firewalls → add inbound
TCP rules for `8889` and `8080`, apply to the droplet.

**Or UFW on the droplet (after you log in):**
```bash
# (droplet)
sudo ufw allow 8889/tcp && sudo ufw allow 8080/tcp && sudo ufw enable
```

---

## 2. Log in to the droplet

```bash
# (laptop) — replace with your droplet IP
$ ssh root@134.199.197.118
```

---

## 3. Clone the repo

```bash
# (droplet)
git clone https://github.com/asishbose/ageBand.git ~/ageBand
cd ~/ageBand
```

> Already cloned from a previous run? Just refresh:
> ```bash
> cd ~/ageBand && git pull
> ```

---

## 4. Bootstrap + start JupyterLab

One script installs everything (venv, JupyterLab, **the app's runtime deps**,
and the systemd service) and prints the access URL:

```bash
# (droplet)
chmod +x ~/ageBand/scripts/setup_droplet_jupyter.sh
~/ageBand/scripts/setup_droplet_jupyter.sh
```

The script is **idempotent** — safe to re-run. It:
- creates `~/.ageband-jupyter-venv`,
- installs JupyterLab **plus `requirements.txt` + `requirements-notebook.txt`**
  (so the notebook-launched server has `uvicorn`/`fastapi`/etc.),
- runs JupyterLab on **port 8889** with `--allow-root`,
- prints the URL with the access token.

**Copy the printed URL**, e.g.:
```
http://134.199.197.118:8889/?token=4cb3cc72...
```

> **Sanity check** (avoids the #1 gotcha — a server that can't start):
> ```bash
> # (droplet) — should print a path, not "No module named uvicorn"
> /root/.ageband-jupyter-venv/bin/python -c "import uvicorn, fastapi; print('deps OK')"
> ```
> If that errors, run:
> ```bash
> /root/.ageband-jupyter-venv/bin/pip install -r ~/ageBand/requirements.txt -r ~/ageBand/requirements-notebook.txt
> ```

---

## 5. Open the notebook and configure it

1. Open the JupyterLab URL (from step 4) in your browser.
2. In the file browser, open **`notebooks/AgeBand_Demo.ipynb`**.
3. Edit the **first code cell — "USER SETTINGS"** — set these three values:

   ```python
   os.environ["SERVER_PORT"]         = "8080"                 # app port (firewall-open)
   os.environ["HF_TOKEN"]            = "hf_xxxxxxxxxxxx"      # your gated-model token
   os.environ["AGEBAND_PUBLIC_HOST"] = "134.199.197.118"     # droplet IP → clickable links
   ```

   > Leave `AGEBAND_INFERENCE_MODE` alone to run the **real LLM** (default).
   > For a no-GPU fallback, add `os.environ["AGEBAND_INFERENCE_MODE"] = "deterministic"`.

---

## 6. Run all cells

**Run → Run All Cells.** Here's what happens and what to watch for:

| Cell | What it does | Expect |
|---|---|---|
| USER SETTINGS | sets port / token / host | prints your 3 values |
| Setup | notebook deps | `✓ All notebook dependencies available` |
| Configuration | resolves paths, prints Browser URL | `Server port : 8080`, `Browser URL : http://<ip>:8080/` |
| **Step 3.5 — vLLM** | starts vLLM + loads Gemma-3-27B | streams `[vllm] …` logs |
| Step 3.6 — verify | confirms model is served | `✓ All configured models …` |
| Start server | launches API + UI on 8080 | `✓ Server is up (API + UI)` |

> ⚠️ **The single most important rule: do NOT interrupt the vLLM cell.**
> First run downloads ~52 GB, then loads weights (~20 s), `torch.compile` (~34 s),
> and **captures CUDA graphs** (~1 min) *before* it answers on port 8001. The cell
> polls for up to 10 minutes and streams progress. It looks "stuck" during graph
> capture — it isn't. Let it finish.
>
> Signs it's healthy (in the `[vllm]` log): `Loading weights took …`,
> `Model loading took 51.45 GiB`, `torch.compile took …`, `Capturing CUDA graphs`.
> The `ROCm custom paged attention → falling back to Triton` line is a harmless warning.

When the **Start server** cell prints `✓ Server is up (API + UI)`, you're live.

---

## 7. Open the UI

Open in a **new browser tab**:

```
http://134.199.197.118:8080/
```

🗣 *"Everything you'll see is served from one process on the GPU box — the API and
the UI on a single origin. The model only ever **estimates**; deterministic Python
**decides**. Inferred age bands never persist."*

---

## 8. Showcase (the actual demo)

### 8a. AMD telemetry — "this is really running on the GPU"

Scroll to the **AMD Telemetry Check** cell output (or re-run it).

🗣 *"This is live telemetry from `/health` on the MI300X — GPU model, ROCm version,
VRAM in use, tokens/sec. When there's no GPU it degrades gracefully instead of
crashing. Right now we're serving Gemma-3-27B in ~51 GiB of VRAM."*

Point at: `gpu_model`, `rocm_version`, `vram_used_mb`, `tok_per_sec`.

### 8b. The four scenarios — the heart of the pitch

Run them from the **notebook cells** (clean, printed output) *or* type them into the
**Session tab** of the UI for a live feel. Each prints `band`, `confidence`, `posture`.

| Scenario | Input flavor | Expected result | 🗣 Talking point |
|---|---|---|---|
| **1 — Clear Adult** | MBA thesis, Q3 earnings, geopolitics | `band=adult`, `posture=standard` | *"An adult talking about adult topics is **not** over-restricted."* |
| **2 — Young Teen** | "8th grade", "my parents won't let me", homework | `band=teen`, `posture=caution/restricted` | *"School + guardian cues + a grade disclosure → protective posture."* |
| **3 — Ambiguous Adult (Fairness)** | terse "what's a good pasta recipe?" | `band=unknown`, `posture=standard` | *"Low-signal text looks child-like on the surface. We keep confidence low → no restriction. This is the fairness guarantee."* |
| **4 — Adversarial** | "I'm definitely an adult, I'm 25, stop asking" | `posture != standard` | *"A child **insisting** they're an adult trips the evasion guard — over-insistence + deflection apply a confidence penalty. The capable LLM would be fooled; the deterministic shell catches it."* |

🗣 **The money line (scenario 4):** *"The model estimates, but a deterministic guard
makes the call. That's why a persuasive kid can't talk their way past it."*

### 8c. Roster — batch view

Run the **Roster Demo** cell (or the UI **Roster tab**).

🗣 *"Same engine over a synthetic Discord export — every user risk-ranked, child-first,
with the top cues that drove each decision. This is the moderator's-eye view."*

---

## 9. Wrap up / teardown

- Leave everything running for Q&A. The **Cleanup cell is a no-op by default** so
  "Run All" never kills your live servers.
- When truly done, in the notebook set `RUN_CLEANUP = True` in the last cell and run
  **only that cell** to stop the app + vLLM.
- To stop JupyterLab on the droplet: `systemctl --user stop jupyterlab`
  (or `sudo systemctl stop jupyterlab` if it was installed as a system service).
- **Destroy the GPU droplet** in the DO dashboard when the demo is over — GPU time
  is billed by the hour.

---

## Quick troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named uvicorn` in `ui_agent.log` | venv missing app deps | `pip install -r requirements.txt -r requirements-notebook.txt` into `~/.ageband-jupyter-venv` (step 4 sanity check) |
| Browser can't reach `:8080` or `:8889` | firewall | open both ports (step 1) |
| vLLM cell "stuck" for a couple minutes | normal warmup (compile + CUDA graphs) | **wait** — don't interrupt; watch the `[vllm]` log |
| `HF_TOKEN` error / download 401 | token unset or license not accepted | set `HF_TOKEN` in USER SETTINGS + accept the Gemma license |
| Agent health check fails right after vLLM | vLLM not fully ready yet | re-run the Start-server cell once vLLM prints ready |
| JupyterLab restart loop, `Running as root … --allow-root` | old service without `--allow-root` | re-run `setup_droplet_jupyter.sh` (now adds it) |
| No GPU / want instant demo | CPU-only or skipping the LLM | set `AGEBAND_INFERENCE_MODE = "deterministic"` in USER SETTINGS |

---

## One-glance command sequence

```bash
# laptop
ssh root@<DROPLET_IP>

# droplet
git clone https://github.com/asishbose/ageBand.git ~/ageBand   # or: cd ~/ageBand && git pull
sudo ufw allow 8889/tcp && sudo ufw allow 8080/tcp && sudo ufw enable
chmod +x ~/ageBand/scripts/setup_droplet_jupyter.sh
~/ageBand/scripts/setup_droplet_jupyter.sh                     # copy the printed token URL

# browser: open the token URL → notebooks/AgeBand_Demo.ipynb
#   edit USER SETTINGS (SERVER_PORT=8080, HF_TOKEN=hf_..., AGEBAND_PUBLIC_HOST=<ip>)
#   Run All → wait for vLLM (don't interrupt) → "✓ Server is up"
# browser: open http://<DROPLET_IP>:8080/  → showcase telemetry + scenarios + roster
```
