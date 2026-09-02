"""
Add fraud-shield (anomaly) columns to assessments.

The Smart Discrepancy & Fraud Shield Engine runs during every scoring pass
and persists its verdict alongside the score: flat columns for SQL-level
queue filtering (risk level, audit requirement, risk score, flag count)
plus a JSONB report carrying the full flags, evidence, and the policy
recommendation shown on reviewer detail pages.

Revision ID: 0004_assessment_anomaly_shield
Revises: 0003_assessment_data_sufficiency
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_assessment_anomaly_shield"
down_revision = "0003_assessment_data_sufficiency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column(
            "anomaly_risk_score",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "assessments",
        sa.Column(
            "anomaly_risk_level",
            sa.String(64),
            nullable=False,
            server_default="clean",
        ),
    )
    op.add_column(
        "assessments",
        sa.Column(
            "anomaly_audit_required",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "assessments",
        sa.Column(
            "anomaly_flags_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "assessments",
        sa.Column("anomaly_report", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assessments", "anomaly_report")
    op.drop_column("assessments", "anomaly_flags_count")
    op.drop_column("assessments", "anomaly_audit_required")
    op.drop_column("assessments", "anomaly_risk_level")
    op.drop_column("assessments", "anomaly_risk_score")
