"""
Add signal_categories_count and non_null_feature_count to assessments.

These make data sufficiency a first-class part of every assessment row,
not just side-channel metadata. A reviewer must be able to see at a
glance how much evidence sits behind a score.

Revision ID: 0003_assessment_data_sufficiency
Revises: 0002_add_training_labels
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_assessment_data_sufficiency"
down_revision = "0002_add_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column(
            "signal_categories_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "assessments",
        sa.Column(
            "non_null_feature_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("assessments", "non_null_feature_count")
    op.drop_column("assessments", "signal_categories_count")
