"""initial schema — all tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00.000000

Design decision: enum columns are stored as VARCHAR (not Postgres native
enum types). This avoids psycopg3's enum-name-vs-value mismatch and makes
the schema portable across Postgres hosting providers (Neon, RDS, local).
The Python-side StrEnumType TypeDecorator handles validation and conversion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── applicants ──────────────────────────────────────────────────────────
    op.create_table(
        "applicants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("identity_reference", sa.String(64), nullable=True, index=True),
        sa.Column("applicant_type", sa.String(32), nullable=True),
        sa.Column("household_size", sa.Integer, nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("district", sa.String(100), nullable=True),
        sa.Column("dependants", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # ── utility_records ─────────────────────────────────────────────────────
    op.create_table(
        "utility_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "applicant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applicants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("utility_type", sa.String(32), nullable=True),
        sa.Column("billing_month", sa.Date, nullable=True),
        sa.Column("amount_billed", sa.Float, nullable=True),
        sa.Column("amount_paid", sa.Float, nullable=True),
        sa.Column("days_late", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # ── academic_records ────────────────────────────────────────────────────
    op.create_table(
        "academic_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "applicant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applicants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("institution", sa.String(200), nullable=True),
        sa.Column("qualification_level", sa.String(32), nullable=True),
        sa.Column("result_value", sa.Float, nullable=True),
        sa.Column("result_scale", sa.String(32), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # ── income_signals ──────────────────────────────────────────────────────
    op.create_table(
        "income_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "applicant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applicants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("declared_monthly_amount", sa.Float, nullable=True),
        sa.Column("evidence_type", sa.String(32), nullable=True),
        sa.Column("confidence_flag", sa.Boolean, nullable=True, default=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # ── assessments ─────────────────────────────────────────────────────────
    op.create_table(
        "assessments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "applicant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applicants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("band", sa.String(16), nullable=False),
        sa.Column("feature_contributions", JSONB, nullable=True),
        sa.Column("model_version", sa.String(32), nullable=False, default="0.1.0"),
        sa.Column("is_rule_based", sa.Boolean, nullable=False, default=False),
        sa.Column("confidence_level", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # ── reviewer_decisions ──────────────────────────────────────────────────
    op.create_table(
        "reviewer_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("reviewer", sa.String(200), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("rationale", sa.String(2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("reviewer_decisions")
    op.drop_table("assessments")
    op.drop_table("income_signals")
    op.drop_table("academic_records")
    op.drop_table("utility_records")
    op.drop_table("applicants")
