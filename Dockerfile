FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

FROM base AS lock-tools
RUN pip install "pip==25.3" "pip-tools==7.5.2"
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip-compile --generate-hashes --strip-extras --allow-unsafe --output-file=requirements.txt pyproject.toml \
    && pip-compile --generate-hashes --strip-extras --allow-unsafe --extra=dev --constraint=requirements.txt --output-file=requirements-dev.txt pyproject.toml \
    && pip-compile --generate-hashes --strip-extras --allow-unsafe --only-build-deps --build-deps-for=wheel --output-file=requirements-build.txt pyproject.toml

FROM base AS runtime
COPY requirements.txt requirements-build.txt ./
RUN pip install --require-hashes --only-binary=:all: -r requirements-build.txt -r requirements.txt

COPY pyproject.toml ./
COPY src/ ./src/

RUN --network=none pip install --no-deps --no-build-isolation . \
    && useradd --system --uid 10001 --no-create-home appuser

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "qa_intelligence.main:app", "--host", "0.0.0.0", "--port", "8000"]
