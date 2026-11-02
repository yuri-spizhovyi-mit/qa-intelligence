# Dependencies and the base image are not locked to immutable versions.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install . \
    && useradd --system --uid 10001 --no-create-home appuser

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "qa_intelligence.main:app", "--host", "0.0.0.0", "--port", "8000"]
