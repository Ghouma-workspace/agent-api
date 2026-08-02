"""V2 schema hardening

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-02

Changes:
  sessions:
    - device_id VARCHAR(64)          — binds refresh tokens to a device
    - last_seen_ip VARCHAR(64)       — updated on every successful token refresh

  conversations:
    - summarized_up_to TIMESTAMPTZ   — tracks which messages have been summarized
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- sessions: device binding and IP tracking ---
    op.add_column(
        "sessions",
        sa.Column("device_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("last_seen_ip", sa.String(64), nullable=True),
    )

    # --- conversations: summarization watermark ---
    op.add_column(
        "conversations",
        sa.Column("summarized_up_to", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "summarized_up_to")
    op.drop_column("sessions", "last_seen_ip")
    op.drop_column("sessions", "device_id")
