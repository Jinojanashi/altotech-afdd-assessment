"""Add indexes used by canonical ontology inspection queries."""

from alembic import op

revision = "20260922_0002"
down_revision = "20260922_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX ontology_entities_kind_idx ON ontology_entities (entity_kind)")
    op.execute("CREATE INDEX equipment_type_idx ON equipment (equipment_type)")
    op.execute("CREATE INDEX telemetry_points_owner_idx ON telemetry_points (owner_equipment_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS telemetry_points_owner_idx")
    op.execute("DROP INDEX IF EXISTS equipment_type_idx")
    op.execute("DROP INDEX IF EXISTS ontology_entities_kind_idx")

