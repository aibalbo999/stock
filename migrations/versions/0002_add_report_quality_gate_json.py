"""Add structured report quality gate payload.

Revision ID: 0002_add_report_quality_gate_json
Revises: 0001_initial_schema
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_report_quality_gate_json"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generated_reports", sa.Column("quality_gate_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("generated_reports", "quality_gate_json")
