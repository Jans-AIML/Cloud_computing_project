FROM public.ecr.aws/lambda/python:3.13

# ── Install Python dependencies ───────────────────────────────────────────────
# --prefer-binary: use pre-built wheels (avoids needing Rust/gcc for mmh3, etc.)
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --upgrade pip --quiet && \
    pip install -r ${LAMBDA_TASK_ROOT}/requirements.txt \
        --no-cache-dir --quiet --prefer-binary

# ── Pre-download fastembed model into the image ───────────────────────────────
# Model: BAAI/bge-small-en-v1.5  (384-dim ONNX, ~22 MB)
# Stored at /var/task/fastembed_cache so it ships with the container.
# At runtime, fastembed_client.py copies it to /tmp (writable) on cold start.
RUN python -c "\
from fastembed import TextEmbedding; \
list(TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/var/task/fastembed_cache').embed(['warmup']))"

# ── Copy application code ─────────────────────────────────────────────────────
COPY app/ ${LAMBDA_TASK_ROOT}/app/

CMD ["app.main.handler"]
