"""Complete ingestion audit, observation history, and current-state schema."""

from alembic import op

revision = "20260922_0003"
down_revision = "20260922_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ingestion_events DROP CONSTRAINT ingestion_events_processing_status_check;
        ALTER TABLE ingestion_events ADD CONSTRAINT ingestion_events_processing_status_check
            CHECK (processing_status IN ('ACCEPTED', 'REJECTED'));
        ALTER TABLE ingestion_attempts DROP CONSTRAINT ingestion_attempts_disposition_check;
        ALTER TABLE ingestion_attempts ADD CONSTRAINT ingestion_attempts_disposition_check
            CHECK (disposition IN ('ACCEPTED', 'DUPLICATE', 'REJECTED'));

        ALTER TABLE telemetry_readings
            ADD COLUMN equipment_id uuid NOT NULL REFERENCES equipment(entity_id),
            ADD COLUMN unit text;
        ALTER TABLE telemetry_readings DROP CONSTRAINT telemetry_readings_quality_check;
        ALTER TABLE telemetry_readings ADD CONSTRAINT telemetry_readings_quality_check
            CHECK (quality IN ('GOOD', 'INVALID', 'UNKNOWN_ID'));
        CREATE UNIQUE INDEX telemetry_readings_event_point_idx
            ON telemetry_readings (event_id, point_id, observed_at);
        CREATE INDEX telemetry_readings_equipment_time_idx
            ON telemetry_readings (equipment_id, observed_at DESC);

        ALTER TABLE current_point_values
            ADD COLUMN equipment_id uuid NOT NULL REFERENCES equipment(entity_id),
            ADD COLUMN unit text;
        ALTER TABLE current_point_values DROP CONSTRAINT current_point_values_quality_check;
        ALTER TABLE current_point_values ADD CONSTRAINT current_point_values_quality_check
            CHECK (quality IN ('GOOD', 'INVALID', 'UNKNOWN_ID'));
        CREATE INDEX current_point_values_equipment_idx ON current_point_values (equipment_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS current_point_values_equipment_idx;
        ALTER TABLE current_point_values DROP CONSTRAINT current_point_values_quality_check;
        ALTER TABLE current_point_values ADD CONSTRAINT current_point_values_quality_check
            CHECK (quality IN ('good', 'missing', 'invalid'));
        ALTER TABLE current_point_values DROP COLUMN unit, DROP COLUMN equipment_id;
        DROP INDEX IF EXISTS telemetry_readings_equipment_time_idx;
        DROP INDEX IF EXISTS telemetry_readings_event_point_idx;
        ALTER TABLE telemetry_readings DROP CONSTRAINT telemetry_readings_quality_check;
        ALTER TABLE telemetry_readings ADD CONSTRAINT telemetry_readings_quality_check
            CHECK (quality IN ('good', 'missing', 'invalid', 'late'));
        ALTER TABLE telemetry_readings DROP COLUMN unit, DROP COLUMN equipment_id;
        ALTER TABLE ingestion_attempts DROP CONSTRAINT ingestion_attempts_disposition_check;
        ALTER TABLE ingestion_attempts ADD CONSTRAINT ingestion_attempts_disposition_check
            CHECK (disposition IN ('first_seen', 'duplicate'));
        ALTER TABLE ingestion_events DROP CONSTRAINT ingestion_events_processing_status_check;
        ALTER TABLE ingestion_events ADD CONSTRAINT ingestion_events_processing_status_check
            CHECK (processing_status IN ('accepted', 'rejected', 'incomplete', 'unknown_equipment'));
        """
    )
