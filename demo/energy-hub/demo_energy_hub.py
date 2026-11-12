import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    device_id: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
    ]
    occurred_at: datetime
    energy_wh: Annotated[int, Field(strict=True, ge=0, le=25000)]

    @field_validator("occurred_at", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> datetime:
        pattern = (
            r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:[0-5]\d"
            r"(?:\.\d{1,6})?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
        )
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError("Use an RFC 3339 timestamp with an explicit UTC offset")
        try:
            return datetime.fromisoformat(value.upper()).astimezone(timezone.utc)
        except OverflowError as exc:
            raise ValueError("Timestamp is outside the supported UTC date range") from exc


def create_app() -> FastAPI:
    app = FastAPI(title="Demo Energy Hub", description="Synthetic in-memory test fixture.")
    events: dict[UUID, Event] = {}
    lock = Lock()

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(Path(__file__).with_name("index.html"))

    @app.post("/v1/events", response_model=Event, status_code=201)
    def submit_event(event: Event, response: Response) -> Event:
        with lock:
            stored = events.get(event.event_id)
            if stored is not None:
                if stored != event:
                    raise HTTPException(409, "Event ID already has different content")
                response.status_code = 200
                return stored
            events[event.event_id] = event
            response.headers["Location"] = f"/v1/events/{event.event_id}"
            return event

    @app.get("/v1/events/{event_id}", response_model=Event)
    def get_event(event_id: UUID) -> Event:
        with lock:
            event = events.get(event_id)
            if event is None:
                raise HTTPException(404, "Event not found")
            return event

    return app


app = create_app()
