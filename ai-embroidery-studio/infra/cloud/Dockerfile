# Single-container API + in-process job threads + pinned Ink/Stitch. Used for Render (Docker context
# ai-embroidery-studio, this file) and Hugging Face Spaces. Listens on $PORT (Render: 10000, Spaces: 7860).
FROM ubuntu:24.04

ARG INKSTITCH_TAG=v3.3.0
ARG INKSTITCH_COMMIT=b0edd96311ece82ee48816dc93466274b12c2a9c

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-wxgtk4.0 xvfb xauth git ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${INKSTITCH_TAG}" https://github.com/inkstitch/inkstitch /opt/inkstitch \
    && test "$(git -C /opt/inkstitch rev-parse HEAD)" = "${INKSTITCH_COMMIT}" \
    && rm -rf /opt/inkstitch/.git

COPY infra/worker/inkstitch-requirements.txt /tmp/inkstitch-requirements.txt
COPY services/requirements.txt /tmp/backend-requirements.txt
RUN python3.12 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps inkex==1.4.1 \
    && grep -v '^inkex' /tmp/inkstitch-requirements.txt > /tmp/rest.txt \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/rest.txt -r /tmp/backend-requirements.txt

# Run as uid 1000 (required by Spaces). ubuntu:24.04 already ships a uid-1000 user ("ubuntu").
RUN mkdir -p /data && chown 1000:1000 /data
WORKDIR /app
COPY --chown=1000:1000 services/ services/
COPY --chown=1000:1000 fixtures/ fixtures/
COPY --chown=1000:1000 tools/ tools/

ENV PATH=/opt/venv/bin:$PATH \
    INKSTITCH_CMD="xvfb-run -a /opt/venv/bin/python /app/services/worker/inkstitch_launcher.py /opt/inkstitch" \
    EMB_DATA_DIR=/data \
    EMB_QUEUE_MODE=thread \
    EMB_WORKER_THREADS=1 \
    EMB_AUTH_MODE=supabase \
    EMB_STORAGE=supabase \
    PORT=7860 \
    MALLOC_ARENA_MAX=2

USER 1000:1000
ENV HOME=/home/ubuntu
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn services.api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
