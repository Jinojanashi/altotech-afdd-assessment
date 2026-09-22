"""Deterministic conversion of source snapshots into transport events."""

import csv
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from afdd.events import TelemetryEvent, TelemetryValue, event_id_for

FILE_CONTRACTS = (
    (
        "ahu_readings.csv", "equipment_id", "AHU",
        {
            "run_status": "RUN", "alarm_status": "ALARM",
            "supply_air_temperature_c": "SAT", "return_air_temperature_c": "RAT",
            "supply_air_temperature_setpoint_c": "SAT_SP",
        },
    ),
    (
        "iaq_readings.csv", "device_id", "IAQ Sensor",
        {"room_temperature_c": "ROOM_TEMP", "relative_humidity_pct": "RH", "co2_ppm": "CO2"},
    ),
    (
        "power_readings.csv", "meter_id", "Electricity Meter",
        {"active_power_kw": "POWER_KW", "cumulative_energy_kwh": "ENERGY_KWH"},
    ),
)


def source_events(source_dir: Path) -> Iterator[TelemetryEvent]:
    for filename, equipment_field, equipment_type, columns in FILE_CONTRACTS:
        with (source_dir / filename).open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                measurements = []
                for column, measurement in columns.items():
                    raw = row[column]
                    if raw == "":
                        continue
                    value: float | str = float(raw) if measurement not in {"RUN", "ALARM"} else raw
                    measurements.append(TelemetryValue(measurement=measurement, value=value))
                yield TelemetryEvent(
                    event_id=event_id_for("candidate-starter-pack", row["source_record_id"]),
                    source_record_id=row["source_record_id"],
                    equipment_id=row[equipment_field],
                    equipment_type=equipment_type,
                    observed_at=row["observed_at"],
                    received_at=datetime.now(UTC),
                    measurements=measurements,
                    source_file=filename,
                )
