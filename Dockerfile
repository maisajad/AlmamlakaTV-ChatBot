# Hugging Face Spaces (Docker SDK). Runs as uid 1000, as Spaces expects.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/user/.cache/huggingface \
    TRANSFORMERS_VERBOSITY=error
WORKDIR /home/user/app

# CPU-only torch first: the default Linux wheel pulls ~2 GB of CUDA libraries we don't need.
# requirements.txt pins torch==2.14.1, which this 2.14.1+cpu build satisfies.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user -r requirements.txt

# Bake the embedding model into the image so startup needs no download.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"
ENV HF_HUB_OFFLINE=1

COPY --chown=user . .

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
