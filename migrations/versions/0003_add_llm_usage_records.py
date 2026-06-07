"""Add LLM usage history records.

Revision ID: 0003_add_llm_usage_records
Revises: 0002_add_report_quality_gate_json
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_add_llm_usage_records"
down_revision = "0002_add_report_quality_gate_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("input_token_estimate", sa.Integer(), nullable=True),
        sa.Column("output_token_estimate", sa.Integer(), nullable=True),
        sa.Column("total_token_estimate", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("cost_tracking_mode", sa.String(length=80), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("retryable_failure_count", sa.Integer(), nullable=True),
        sa.Column("fallback_path_used", sa.Boolean(), nullable=False),
        sa.Column("primary_failure_category", sa.String(length=120), nullable=True),
        sa.Column("models_tried_json", sa.Text(), nullable=False),
        sa.Column("attempts_json", sa.Text(), nullable=False),
        sa.Column("observability_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_records_model", "llm_usage_records", ["model"])
    op.create_index("ix_llm_usage_records_operation", "llm_usage_records", ["operation"])
    op.create_index("ix_llm_usage_records_report_id", "llm_usage_records", ["report_id"])
    op.create_index("ix_llm_usage_records_run_id", "llm_usage_records", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_records_run_id", table_name="llm_usage_records")
    op.drop_index("ix_llm_usage_records_report_id", table_name="llm_usage_records")
    op.drop_index("ix_llm_usage_records_operation", table_name="llm_usage_records")
    op.drop_index("ix_llm_usage_records_model", table_name="llm_usage_records")
    op.drop_table("llm_usage_records")
