"""Create relational ontology and telemetry foundation."""

from alembic import op

revision = "20260922_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "timescaledb"')
    op.execute(
        """
        CREATE TABLE ontology_entities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id text NOT NULL UNIQUE,
            entity_kind text NOT NULL CHECK (entity_kind IN ('space', 'equipment', 'point')),
            brick_class text NOT NULL,
            name text NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE spaces (
            entity_id uuid PRIMARY KEY REFERENCES ontology_entities(id) ON DELETE CASCADE,
            space_type text NOT NULL,
            usage_type text,
            property_type text
        );

        CREATE TABLE equipment (
            entity_id uuid PRIMARY KEY REFERENCES ontology_entities(id) ON DELETE CASCADE,
            equipment_type text NOT NULL
        );

        CREATE TABLE telemetry_points (
            entity_id uuid PRIMARY KEY REFERENCES ontology_entities(id) ON DELETE CASCADE,
            owner_equipment_id uuid NOT NULL REFERENCES equipment(entity_id),
            source_name text NOT NULL,
            value_type text NOT NULL,
            unit text,
            expected_interval_seconds integer NOT NULL CHECK (expected_interval_seconds > 0),
            UNIQUE (owner_equipment_id, source_name)
        );

        CREATE TABLE ontology_relationships (
            subject_id uuid NOT NULL REFERENCES ontology_entities(id) ON DELETE CASCADE,
            predicate text NOT NULL CHECK (
                predicate IN (
                    'hasPart', 'isPartOf', 'hasLocation', 'isLocationOf', 'feeds', 'hasPoint', 'meters'
                )
            ),
            object_id uuid NOT NULL REFERENCES ontology_entities(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (subject_id, predicate, object_id),
            CHECK (subject_id <> object_id)
        );

        CREATE INDEX ontology_relationships_object_idx
            ON ontology_relationships (object_id, predicate);

        CREATE TABLE ingestion_events (
            event_id uuid PRIMARY KEY,
            schema_version smallint NOT NULL,
            source_system text NOT NULL,
            source_record_id text NOT NULL,
            equipment_source_id text NOT NULL,
            observed_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            source_file text NOT NULL,
            payload jsonb NOT NULL,
            processing_status text NOT NULL CHECK (
                processing_status IN ('accepted', 'rejected', 'incomplete', 'unknown_equipment')
            ),
            reason text,
            UNIQUE (source_system, source_record_id)
        );

        CREATE INDEX ingestion_events_observed_at_idx ON ingestion_events (observed_at DESC);
        CREATE INDEX ingestion_events_status_idx ON ingestion_events (processing_status, received_at DESC);

        CREATE TABLE ingestion_attempts (
            attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id uuid NOT NULL,
            source_system text NOT NULL,
            source_record_id text NOT NULL,
            received_at timestamptz NOT NULL,
            disposition text NOT NULL CHECK (disposition IN ('first_seen', 'duplicate')),
            canonical_event_id uuid NOT NULL REFERENCES ingestion_events(event_id),
            details jsonb NOT NULL DEFAULT '{}'::jsonb
        );

        CREATE INDEX ingestion_attempts_source_record_idx
            ON ingestion_attempts (source_system, source_record_id, received_at DESC);
        CREATE INDEX ingestion_attempts_disposition_idx
            ON ingestion_attempts (disposition, received_at DESC);

        CREATE TABLE telemetry_readings (
            observed_at timestamptz NOT NULL,
            point_id uuid NOT NULL REFERENCES telemetry_points(entity_id),
            event_id uuid NOT NULL REFERENCES ingestion_events(event_id),
            received_at timestamptz NOT NULL,
            numeric_value double precision,
            text_value text,
            quality text NOT NULL CHECK (quality IN ('good', 'missing', 'invalid', 'late')),
            PRIMARY KEY (observed_at, point_id, event_id),
            CHECK (num_nonnulls(numeric_value, text_value) <= 1)
        );

        SELECT create_hypertable('telemetry_readings', by_range('observed_at'), if_not_exists => TRUE);

        CREATE TABLE current_point_values (
            point_id uuid PRIMARY KEY REFERENCES telemetry_points(entity_id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            event_id uuid NOT NULL REFERENCES ingestion_events(event_id),
            numeric_value double precision,
            text_value text,
            quality text NOT NULL CHECK (quality IN ('good', 'missing', 'invalid')),
            CHECK (num_nonnulls(numeric_value, text_value) <= 1)
        );

        CREATE TABLE afdd_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_key text NOT NULL,
            version integer NOT NULL CHECK (version > 0),
            severity text NOT NULL,
            threshold double precision NOT NULL,
            duration_seconds integer NOT NULL CHECK (duration_seconds > 0),
            freshness_seconds integer NOT NULL CHECK (freshness_seconds > 0),
            enabled boolean NOT NULL DEFAULT true,
            definition jsonb NOT NULL,
            UNIQUE (rule_key, version)
        );

        CREATE TABLE afdd_rule_overrides (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id uuid NOT NULL REFERENCES afdd_rules(id),
            property_id uuid NOT NULL REFERENCES spaces(entity_id),
            threshold double precision,
            duration_seconds integer CHECK (duration_seconds > 0),
            UNIQUE (rule_id, property_id)
        );

        CREATE TABLE afdd_issues (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id uuid NOT NULL REFERENCES afdd_rules(id),
            equipment_id uuid NOT NULL REFERENCES equipment(entity_id),
            occurrence integer NOT NULL DEFAULT 1 CHECK (occurrence > 0),
            status text NOT NULL CHECK (status IN ('open', 'closed')),
            opened_at timestamptz NOT NULL,
            closed_at timestamptz,
            evidence jsonb NOT NULL,
            CHECK ((status = 'open' AND closed_at IS NULL) OR status = 'closed'),
            UNIQUE (rule_id, equipment_id, occurrence)
        );

        CREATE UNIQUE INDEX one_open_issue_per_rule_equipment
            ON afdd_issues (rule_id, equipment_id) WHERE status = 'open';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS afdd_issues;
        DROP TABLE IF EXISTS afdd_rule_overrides;
        DROP TABLE IF EXISTS afdd_rules;
        DROP TABLE IF EXISTS current_point_values;
        DROP TABLE IF EXISTS telemetry_readings;
        DROP TABLE IF EXISTS ingestion_attempts;
        DROP TABLE IF EXISTS ingestion_events;
        DROP TABLE IF EXISTS ontology_relationships;
        DROP TABLE IF EXISTS telemetry_points;
        DROP TABLE IF EXISTS equipment;
        DROP TABLE IF EXISTS spaces;
        DROP TABLE IF EXISTS ontology_entities;
        """
    )
