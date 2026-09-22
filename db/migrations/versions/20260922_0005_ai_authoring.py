"""Persist safe, auditable AI-assisted rule-authoring workflows."""

from alembic import op

revision = "20260922_0005"
down_revision = "20260922_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai_authoring_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_prompt text NOT NULL,
            state text NOT NULL CHECK (state IN (
                'RECEIVED','INTERPRETING','DISCOVERING','VALIDATING','PREVIEWING',
                'NEEDS_CLARIFICATION','READY_FOR_REVIEW','CONFIRMED','ACTIVATED',
                'REJECTED','FAILED','STOPPED'
            )),
            interpreted_intent jsonb,
            structured_draft jsonb,
            reviewed_draft jsonb,
            clarification_question text,
            clarification_history jsonb NOT NULL DEFAULT '[]'::jsonb,
            tool_trace jsonb NOT NULL DEFAULT '[]'::jsonb,
            state_trace jsonb NOT NULL DEFAULT '[]'::jsonb,
            validation_result jsonb,
            target_preview jsonb,
            warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
            human_confirmed_at timestamptz,
            activation_result jsonb,
            provider text NOT NULL,
            model text NOT NULL,
            prompt_version text NOT NULL,
            schema_version text NOT NULL,
            model_calls integer NOT NULL DEFAULT 0,
            retry_count integer NOT NULL DEFAULT 0,
            latency_ms integer NOT NULL DEFAULT 0,
            stop_reason text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ai_authoring_state_updated_idx
            ON ai_authoring_requests (state, updated_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE ai_authoring_requests")
