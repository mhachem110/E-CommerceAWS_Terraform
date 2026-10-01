FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 app \
    && mkdir /data \
    && chown app:app /data

ARG SERVICE
COPY services/__init__.py services/__init__.py
COPY services/${SERVICE}.py services/main.py
USER app
EXPOSE 8000
CMD ["uvicorn", "services.main:app", "--host", "0.0.0.0", "--port", "8000"]
