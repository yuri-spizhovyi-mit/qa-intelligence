FROM mcr.microsoft.com/playwright/python:v1.64.1-noble@sha256:330d401ae23c905896a0c26c66c36fc971b621519e7b11b435a8328d7bf6e031 AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /runner

FROM base AS lock-tools
RUN pip install "pip==25.3" "pip-tools==7.5.2"
COPY infra/runner/requirements.in ./
RUN pip-compile --generate-hashes --output-file=requirements.txt requirements.in

FROM base AS runtime
COPY infra/runner/requirements.txt ./
RUN pip install --require-hashes --only-binary=:all: -r requirements.txt \
    && test "$(id -u pwuser)" = "1001"
COPY infra/runner/controller.py infra/runner/runner_contract.py ./
ENV HOME=/tmp/pw-home \
    XDG_CACHE_HOME=/tmp/pw-cache \
    PYTHONPATH=/runner
WORKDIR /work
USER 1001:1001
ENTRYPOINT ["python", "/runner/controller.py"]
CMD ["--preflight"]
