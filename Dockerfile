# FastAPI forecast service for Azm. The trained model is not baked in:
# mount the folder holding azm_demo.joblib at /app/models (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AZM_MODEL_PATH=/app/models/azm_demo.joblib

WORKDIR /app

COPY requirements-serve.lock.txt ./
RUN pip install -r requirements-serve.lock.txt

COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-deps . \
    && useradd --create-home appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "lebanon_energy.api.service:app", "--host", "0.0.0.0", "--port", "8000"]
