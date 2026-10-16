# Small image for a 512 MB free instance: no torch, embeddings run on ONNX Runtime.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/user/.cache/huggingface
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Bake the int8 embedding model (118 MB) into the image so startup needs no download.
COPY --chown=user app/__init__.py app/embeddings.py app/
RUN python -c "import app.embeddings as e; e.OnnxEmbedder()"
ENV HF_HUB_OFFLINE=1

COPY --chown=user . .

# Render (and most hosts) pass the port in $PORT.
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
