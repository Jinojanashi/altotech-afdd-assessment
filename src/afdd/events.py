from datetime import datetime
from typing import Any, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field


def event_id_for(source_system: str, source_record_id: str) -> UUID:
    """Return a stable event ID so replayed source records keep the same business identity."""

    return uuid5(NAMESPACE_URL, f"afdd:{source_system}:{source_record_id}")


class TelemetryValue(BaseModel):
    source_point_id: str
    value: float | str | bool | None
    unit: str | None = None
    quality: Literal["good", "missing", "invalid"] = "good"


class TelemetryEvent(BaseModel):
    """Versioned transport contract; source observation and platform receipt stay distinct."""

    schema_version: Literal[1] = 1
    event_id: UUID
    source_system: str = "candidate-starter-pack"
    source_record_id: str
    equipment_id: str
    observed_at: datetime
    received_at: datetime
    values: list[TelemetryValue] = Field(default_factory=list)
    source_file: str
