# Streamlit operator page. It holds no model: it only calls the API (API_URL)
# and reads the meter history file mounted at /app/data (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    API_URL=http://api:8000 \
    AZM_HISTORY_CSV=/app/data/hourly_data.csv

WORKDIR /app

COPY requirements-app.lock.txt ./
RUN pip install -r requirements-app.lock.txt

COPY .streamlit ./.streamlit
COPY src/lebanon_energy/app ./src/lebanon_energy/app
RUN useradd --create-home appuser
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "src/lebanon_energy/app/main.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
