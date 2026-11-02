from fastapi import FastAPI

app = FastAPI(title="QA Intelligence")


@app.get("/health")
def health() -> dict[str, str]:
    """Process liveness only; makes no provider, database, or environment access."""
    return {"status": "ok"}
