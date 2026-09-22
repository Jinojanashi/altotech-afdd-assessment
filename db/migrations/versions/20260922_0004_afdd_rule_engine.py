"""Create versioned AFDD rules, deterministic state, and issue evidence."""

from alembic import op

revision = "20260922_0004"
down_revision = "20260922_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS one_open_issue_per_rule_equipment;
        DROP TABLE afdd_issues;
        DROP TABLE afdd_rule_overrides;
        DROP TABLE afdd_rules;

        CREATE TABLE afdd_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_key text NOT NULL UNIQUE,
            display_name text NOT NULL,
            active_version_id uuid,
            enabled boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            activated_at timestamptz,
            disabled_at timestamptz
        );

        CREATE TABLE afdd_rule_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id uuid NOT NULL REFERENCES afdd_rules(id) ON DELETE CASCADE,
            version integer NOT NULL CHECK (version > 0),
            severity text NOT NULL CHECK (severity IN ('Critical', 'Warning', 'Info')),
            scope_config jsonb NOT NULL,
            logic_config jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (rule_id, version),
            UNIQUE (id, rule_id)
        );

        ALTER TABLE afdd_rules ADD CONSTRAINT afdd_rules_active_version_fk
            FOREIGN KEY (active_version_id) REFERENCES afdd_rule_versions(id) ON DELETE SET NULL;

        CREATE TABLE afdd_rule_overrides (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_version_id uuid NOT NULL REFERENCES afdd_rule_versions(id) ON DELETE CASCADE,
            property_id uuid NOT NULL REFERENCES spaces(entity_id),
            threshold double precision CHECK (threshold > 0),
            duration_seconds integer CHECK (duration_seconds > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (rule_version_id, property_id),
            CHECK (threshold IS NOT NULL OR duration_seconds IS NOT NULL)
        );

        CREATE TABLE afdd_evaluation_states (
            rule_version_id uuid NOT NULL REFERENCES afdd_rule_versions(id) ON DELETE CASCADE,
            equipment_id uuid NOT NULL REFERENCES equipment(entity_id) ON DELETE CASCADE,
            state text NOT NULL CHECK (state IN ('NORMAL', 'QUALIFYING', 'OPEN')),
            last_observed_at timestamptz,
            qualifying_started_at timestamptz,
            qualifying_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (rule_version_id, equipment_id)
        );

        CREATE TABLE afdd_issues (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id uuid NOT NULL REFERENCES afdd_rules(id),
            rule_version_id uuid NOT NULL REFERENCES afdd_rule_versions(id),
            equipment_id uuid NOT NULL REFERENCES equipment(entity_id),
            occurrence integer NOT NULL CHECK (occurrence > 0),
            severity text NOT NULL CHECK (severity IN ('Critical', 'Warning', 'Info')),
            status text NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
            qualifying_started_at timestamptz NOT NULL,
            opened_at timestamptz NOT NULL,
            closed_at timestamptz,
            threshold double precision NOT NULL,
            duration_seconds integer NOT NULL,
            effective_override jsonb NOT NULL DEFAULT '{}'::jsonb,
            evidence jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((status = 'OPEN' AND closed_at IS NULL) OR
                   (status = 'CLOSED' AND closed_at IS NOT NULL)),
            UNIQUE (rule_version_id, equipment_id, occurrence)
        );

        CREATE UNIQUE INDEX one_open_issue_per_rule_version_equipment
            ON afdd_issues (rule_version_id, equipment_id) WHERE status = 'OPEN';
        CREATE INDEX afdd_issues_status_opened_idx ON afdd_issues (status, opened_at DESC);
        CREATE INDEX afdd_rule_versions_rule_idx ON afdd_rule_versions (rule_id, version DESC);

        CREATE FUNCTION reject_afdd_version_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'AFDD rule versions and overrides are immutable';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER afdd_rule_versions_immutable
            BEFORE UPDATE ON afdd_rule_versions
            FOR EACH ROW EXECUTE FUNCTION reject_afdd_version_update();
        CREATE TRIGGER afdd_rule_overrides_immutable
            BEFORE UPDATE ON afdd_rule_overrides
            FOR EACH ROW EXECUTE FUNCTION reject_afdd_version_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS afdd_rule_overrides_immutable ON afdd_rule_overrides;
        DROP TRIGGER IF EXISTS afdd_rule_versions_immutable ON afdd_rule_versions;
        DROP FUNCTION IF EXISTS reject_afdd_version_update();
        DROP TABLE afdd_issues;
        DROP TABLE afdd_evaluation_states;
        ALTER TABLE afdd_rules DROP CONSTRAINT afdd_rules_active_version_fk;
        DROP TABLE afdd_rule_overrides;
        DROP TABLE afdd_rule_versions;
        DROP TABLE afdd_rules;

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
