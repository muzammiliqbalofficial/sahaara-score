"""
Add case_brief JSONB column to assessments for caching bilingual briefs.

The case brief service generates English executive briefs and Urdu
applicant explanations on demand.  Caching the result on the assessment
row means repeated requests (reviewer reloads, donor export) are instant
— no Qwen API round-trip needed.

Revision ID: 0005_assessment_case_brief
Revises: 0004_assessment_anomaly_shield
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_assessment_case_brief"
down_revision = "0004_assessment_anomaly_shield"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column("case_brief", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assessments", "case_brief")
