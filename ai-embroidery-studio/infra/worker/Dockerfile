# Gate A worker image: pinned Ink/Stitch (from source) + our validation code.
# Build from ai-embroidery-studio/:  docker build -f infra/worker/Dockerfile -t emb-worker:gate-a .
FROM ubuntu:24.04

ARG INKSTITCH_TAG=v3.3.0
ARG INKSTITCH_COMMIT=b0edd96311ece82ee48816dc93466274b12c2a9c

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-wxgtk4.0 xvfb xauth git ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Pinned Ink/Stitch source: the build fails if the tag no longer points at the expected commit.
RUN git clone --depth 1 --branch "${INKSTITCH_TAG}" https://github.com/inkstitch/inkstitch /opt/inkstitch \
    && test "$(git -C /opt/inkstitch rev-parse HEAD)" = "${INKSTITCH_COMMIT}" \
    && rm -rf /opt/inkstitch/.git

COPY infra/worker/inkstitch-requirements.txt /tmp/inkstitch-requirements.txt
COPY services/requirements.txt /tmp/backend-requirements.txt
RUN python3.12 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps inkex==1.4.1 \
    && grep -v '^inkex' /tmp/inkstitch-requirements.txt > /tmp/rest.txt \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/rest.txt -r /tmp/backend-requirements.txt

RUN useradd --create-home --uid 10001 worker && mkdir -p /data && chown worker /data
WORKDIR /app
COPY services/ services/
COPY fixtures/ fixtures/
COPY tools/ tools/
COPY tests/ tests/

# wxPython needs an X display even for CLI runs, so each job gets a throwaway Xvfb.
ENV PATH=/opt/venv/bin:$PATH \
    INKSTITCH_CMD="xvfb-run -a /opt/venv/bin/python /app/services/worker/inkstitch_launcher.py /opt/inkstitch"

USER worker
# Default command = Gate A smoke test (run with --network=none). docker-compose.yml
# reuses this image for the API (uvicorn) and the RQ worker.
CMD ["python", "-m", "services.worker.gate_a", "--fixtures", "fixtures", "--out", "/tmp/gate-a"]
