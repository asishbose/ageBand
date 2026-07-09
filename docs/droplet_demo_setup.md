# Running the Full Demo on a Fresh DigitalOcean Droplet

This guide turns a brand-new Ubuntu droplet into a running AgeBand demo in four
manual steps.  After that, opening the notebook and clicking **Run All** is the
only step needed for each subsequent demo run.

> **No AMD GPU on a standard droplet** — vLLM will print a clear warning and ask
> you to choose between CPU mode (very slow) or deterministic mode (instant, no
> model required).  For real GPU performance use an
> [AMD Dev Cloud](https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html)
> instance and refer to `docs/benchmarks_mi300x.md`.

---

## 1. Create the droplet

| Setting | Recommended |
|---|---|
| Image | Ubuntu 24.04 LTS x64 |
| Size | 4 vCPU / 8 GB RAM (Basic, $48/mo) — for deterministic mode only; LLM mode needs a GPU VM |
| Region | Closest to your demo audience |
| Authentication | SSH key (password login is less secure) |

After the droplet is created, note its **public IP** (shown in the DO dashboard).

## 2. Open firewall ports

The demo needs three ports reachable from your browser:

| Port | Purpose |
|---|---|
| `8888` | JupyterLab (set up by the bootstrap script) |
| `8080` | AgeBand API + UI (combined server started by the notebook) |
| `8001` | vLLM OpenAI-compatible endpoint (started by the notebook on GPU VMs) |

**Option A — DigitalOcean Cloud Firewall (recommended):**
1. Dashboard → **Networking** → **Firewalls** → **Create Firewall**
2. Add Inbound Rules: TCP on ports `8888`, `8080`, `8001`
3. Apply the firewall to your droplet

**Option B — UFW on the droplet:**
```bash
sudo ufw allow 8888/tcp && sudo ufw allow 8080/tcp && sudo ufw allow 8001/tcp
sudo ufw enable
```

## 3. Bootstrap JupyterLab (one time)

SSH into the droplet and run the bootstrap script from the repo.  You can either
clone the repo first, or just `curl` the script directly:

```bash
# Clone the repo (then run the script inside it)
git clone --depth 1 https://github.com/asishbose/ageBand.git ~/ageBand
chmod +x ~/ageBand/scripts/setup_droplet_jupyter.sh
~/ageBand/scripts/setup_droplet_jupyter.sh
```

The script:
- Installs Python 3 + venv if not already present
- Creates `~/.ageband-jupyter-venv` and installs JupyterLab into it
- Generates a random access token stored in `~/.ageband-jupyter-token`
- Registers a **systemd user service** (`jupyterlab.service`) that starts on
  boot and survives SSH disconnects
- Prints the exact access URL including the token

**Expected output:**
```
✓ Ubuntu detected
✓ JupyterLab installed in /root/.ageband-jupyter-venv
✓ New access token generated
✓ systemd service file written to ...
✓ JupyterLab service started successfully

═══════════════════════════════════════════════════════════════════
  JupyterLab is running on port 8888

  Open this URL in your browser (from any machine):

    http://203.0.113.42:8888/?token=a1b2c3d4...

  ── FIREWALL ────────────────────────────────────────────────────
  ...
```

Open the printed URL in your browser to verify JupyterLab loads.

**Re-running the script is safe** (idempotent): it will print the existing
access info rather than starting a second JupyterLab instance.

### Managing the JupyterLab service

```bash
# Check status
systemctl --user status jupyterlab

# Restart (e.g. after a server reboot)
systemctl --user restart jupyterlab

# Stop
systemctl --user stop jupyterlab

# View logs
journalctl --user -u jupyterlab -f
```

## 4. Open the notebook and run the demo

1. Open the JupyterLab URL in your browser.
2. Navigate to `notebooks/AgeBand_Demo.ipynb` in the file browser.
3. Click **Run** → **Run All Cells**.
4. The notebook will:
   - Detect the `LOCAL_API_BASE` (default `http://localhost:8001/v1`)
   - **Step 3.5**: Check whether vLLM is already running at that endpoint
     - If already running → reuse it
     - If not running and this is a local AMD GPU machine → start vLLM automatically
     - If no AMD GPU detected → print a clear warning with two choices
   - Start the AgeBand agent (combined API + UI server on port 8080)
   - Display the live demo UI embedded in the notebook and print the browser URL

5. Open `http://<your-droplet-ip>:8080/` in a separate browser tab for the
   full-screen UI.

---

## GPU path: AMD Dev Cloud / AMD ROCm droplet

If you are on a machine with an AMD GPU (e.g. AMD Dev Cloud MI300X), the
notebook auto-detects it and starts vLLM using the **Docker ROCm container**:

```bash
docker run --rm --network=host --device=/dev/kfd --device=/dev/dri \
  --group-add video --ipc=host --shm-size 16G \
  -e HF_TOKEN=$HF_TOKEN -e VLLM_HOST_IP=127.0.0.1 -e GLOO_SOCKET_IFNAME=lo \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai-rocm:v0.23.0 \
  google/gemma-3-27b-it --host 0.0.0.0 --port 8001
```

This matches the command documented in `docs/benchmarks_mi300x.md` (tested on
AMD Instinct MI300X, 2026-07-09).

**HuggingFace token:** Gemma is a gated model — accept the license at
<https://huggingface.co/google/gemma-3-27b-it> then set `HF_TOKEN` before
running the notebook:

```python
import os; os.environ["HF_TOKEN"] = "hf_..."
```

The notebook will fail with a clear message if `HF_TOKEN` is missing for a
gated model.

**First-run model download:** Gemma 3 27B is ~54 GB.  The notebook streams
vLLM's startup output so you can watch progress rather than staring at a
silent cell.  Subsequent runs use the cached weights (`~/.cache/huggingface`).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser can't reach JupyterLab | Port 8888 blocked | Check firewall rules (step 2) |
| `systemctl --user` errors | `systemd` not running as user session | Run `loginctl enable-linger $(whoami)` and retry |
| vLLM startup timed out | Model download interrupted or not enough VRAM | Check `~/.cache/huggingface`, free disk space, VRAM |
| Agent health check fails | vLLM not yet ready | Re-run cell 3.5 — vLLM may still be loading |
| `HF_TOKEN` error | Token not set | Set `HF_TOKEN` (see GPU path section above) |
| No AMD GPU warning | CPU-only VM (standard droplet) | Use `INFERENCE_MODE=deterministic` (step 3 of the notebook config cell) |
