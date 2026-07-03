FROM python:3.12-slim AS builder

WORKDIR /build

# Install dependencies into a venv so the final image stays lean
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="ageband-agent"
LABEL org.opencontainers.image.description="AgeBand passive age-band inference service"
LABEL org.opencontainers.image.source="https://github.com/your-org/ageband"

# Non-root user for safety
RUN useradd -m -u 1000 ageband
WORKDIR /app

# Copy venv from builder
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Copy application source
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY pyproject.toml .

# Environment defaults — override at runtime via env vars or Helm values
ENV LOCAL_API_BASE="http://localhost:8000/v1" \
    LOCAL_MODEL="Qwen/Qwen2.5-7B-Instruct" \
    LOCAL_API_KEY="EMPTY" \
    PLANNER_MAX_ITERATIONS="8" \
    GATE_CONFIDENCE_THRESHOLD="0.85" \
    GATE_MIN_TURNS="2" \
    LOG_LEVEL="INFO"

USER ageband
EXPOSE 8080

# Health-check: agent HTTP endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8080/health', timeout=4).raise_for_status()"

CMD ["python", "-m", "uvicorn", "src.orchestration.api:app", "--host", "0.0.0.0", "--port", "8080"]
