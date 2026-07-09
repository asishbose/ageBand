#!/usr/bin/env bash
# setup_droplet_jupyter.sh — one-time JupyterLab bootstrap for a DigitalOcean Ubuntu droplet.
#
# Safe to re-run: idempotent. Running it a second time when JupyterLab is already
# running prints the existing access URL rather than starting a second instance.
#
# Targets: Ubuntu 22.04 / 24.04 (standard DO droplet images).
#
# Usage:
#   chmod +x scripts/setup_droplet_jupyter.sh
#   ./scripts/setup_droplet_jupyter.sh
#
# What this does NOT install: vLLM, model weights, CUDA/ROCm.
# Those are installed by the notebook at run time, so the model/version
# choice stays configurable per-run rather than baked into a one-time setup.
set -euo pipefail

VENV_DIR="${HOME}/.ageband-jupyter-venv"
JUPYTER_PORT="8888"
SERVICE_NAME="jupyterlab"
TOKEN_FILE="${HOME}/.ageband-jupyter-token"
SERVICE_FILE="${HOME}/.config/systemd/user/${SERVICE_NAME}.service"

# ── 1. OS check ───────────────────────────────────────────────────────────────
if grep -qi ubuntu /etc/os-release 2>/dev/null; then
    echo "✓ Ubuntu detected"
else
    echo "WARNING: This script targets Ubuntu. Detected OS may differ — proceeding anyway."
    cat /etc/os-release 2>/dev/null | head -5 || true
fi

# ── 2. Install Python 3 + venv if needed ──────────────────────────────────────
if ! command -v python3 &>/dev/null || ! python3 -c "import venv" 2>/dev/null; then
    echo "Installing Python 3 + venv …"
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv
    echo "✓ Python installed: $(python3 --version)"
else
    echo "✓ Python already present: $(python3 --version)"
fi

# ── 3. Create dedicated venv + install JupyterLab ─────────────────────────────
if [ -f "${VENV_DIR}/bin/jupyter" ]; then
    JUPYTER_VERSION=$("${VENV_DIR}/bin/jupyter" --version 2>/dev/null | head -1 || echo "unknown")
    echo "✓ JupyterLab already installed in ${VENV_DIR} (${JUPYTER_VERSION})"
else
    echo "Creating venv and installing JupyterLab …"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
    "${VENV_DIR}/bin/pip" install --quiet jupyterlab
    echo "✓ JupyterLab installed in ${VENV_DIR}"
fi

# ── 4. Generate (or load) random access token ─────────────────────────────────
if [ ! -f "${TOKEN_FILE}" ]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "${TOKEN_FILE}"
    chmod 600 "${TOKEN_FILE}"
    echo "✓ New access token generated"
else
    echo "✓ Existing access token loaded"
fi
TOKEN=$(cat "${TOKEN_FILE}")

# ── 5. Write systemd user service ─────────────────────────────────────────────
mkdir -p "${HOME}/.config/systemd/user"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=JupyterLab for AgeBand demo
After=network.target

[Service]
Type=simple
WorkingDirectory=%h
ExecStart=${VENV_DIR}/bin/jupyter lab \\
    --no-browser \\
    --ip=0.0.0.0 \\
    --port=${JUPYTER_PORT} \\
    --ServerApp.token=${TOKEN} \\
    --ServerApp.allow_origin='*' \\
    --ServerApp.disable_check_xsrf=True
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
echo "✓ systemd service file written to ${SERVICE_FILE}"

# ── 6. Enable lingering so the service survives SSH disconnect ─────────────────
# loginctl enable-linger lets user-level services run without an active login session.
if loginctl enable-linger "$(whoami)" 2>/dev/null; then
    echo "✓ User lingering enabled"
else
    echo "NOTE: loginctl enable-linger failed (may already be set or not available) — continuing"
fi

# ── 7. Enable + start/restart the systemd service ─────────────────────────────
systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}" 2>/dev/null || true

if systemctl --user is-active --quiet "${SERVICE_NAME}"; then
    echo "ℹ️  JupyterLab service is already running — no restart needed"
    echo "   To restart: systemctl --user restart ${SERVICE_NAME}"
else
    systemctl --user start "${SERVICE_NAME}"
    # Give it a moment to bind the port
    sleep 2
    if systemctl --user is-active --quiet "${SERVICE_NAME}"; then
        echo "✓ JupyterLab service started successfully"
    else
        echo "ERROR: JupyterLab service failed to start. Checking logs:"
        journalctl --user -u "${SERVICE_NAME}" -n 20 --no-pager || true
        exit 1
    fi
fi

# ── 8. Detect public IP ────────────────────────────────────────────────────────
PUBLIC_IP=""
# Try DO's metadata API first (most reliable on a DO droplet), then ipify, then hostname
PUBLIC_IP=$(curl -sf --max-time 3 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address \
            2>/dev/null || true)
if [ -z "${PUBLIC_IP}" ]; then
    PUBLIC_IP=$(curl -sf --max-time 3 https://api.ipify.org 2>/dev/null || \
                curl -sf --max-time 3 https://ifconfig.me 2>/dev/null || \
                hostname -I 2>/dev/null | awk '{print $1}' || \
                echo "YOUR_DROPLET_IP")
fi

# ── 9. Print access info ───────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  JupyterLab is running on port ${JUPYTER_PORT}"
echo ""
echo "  Open this URL in your browser (from any machine):"
echo ""
echo "    http://${PUBLIC_IP}:${JUPYTER_PORT}/?token=${TOKEN}"
echo ""
echo "  ── FIREWALL ────────────────────────────────────────────────────"
echo "  You must open port ${JUPYTER_PORT}/tcp for the URL above to work:"
echo ""
echo "  Option A — DigitalOcean Cloud Firewall (recommended):"
echo "    Dashboard → Networking → Firewalls → Add Rule"
echo "    Type: TCP, Ports: ${JUPYTER_PORT}, Source: Your IP (or 0.0.0.0/0)"
echo ""
echo "  Option B — UFW on this droplet:"
echo "    sudo ufw allow ${JUPYTER_PORT}/tcp && sudo ufw status"
echo ""
echo "  The demo notebook also needs ports 8080 (agent) and 8081 (UI)."
echo "  Open those the same way when you run the notebook:"
echo "    sudo ufw allow 8080/tcp && sudo ufw allow 8081/tcp"
echo ""
echo "  ── MANAGING THE SERVICE ────────────────────────────────────────"
echo "  Status:   systemctl --user status  ${SERVICE_NAME}"
echo "  Restart:  systemctl --user restart ${SERVICE_NAME}"
echo "  Stop:     systemctl --user stop    ${SERVICE_NAME}"
echo "  Logs:     journalctl --user -u     ${SERVICE_NAME} -f"
echo "═══════════════════════════════════════════════════════════════════"
