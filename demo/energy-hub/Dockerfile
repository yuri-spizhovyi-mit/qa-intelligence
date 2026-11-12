FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /demo
COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
    && useradd --system --uid 10001 --no-create-home appuser
COPY demo/energy-hub/demo_energy_hub.py demo/energy-hub/index.html ./
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "demo_energy_hub:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
