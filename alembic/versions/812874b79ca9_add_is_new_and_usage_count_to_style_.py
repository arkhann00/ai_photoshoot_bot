"""add is_new and usage_count to style_prompts

Revision ID: 812874b79ca9
Revises: 93773858a74e
Create Date: 2025-12-19 15:25:47.068890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '812874b79ca9'
down_revision: Union[str, Sequence[str], None] = '93773858a74e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "style_prompts",
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "style_prompts",
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # (опционально) индекс, если будешь сортировать/топы строить
    op.create_index("ix_style_prompts_usage_count", "style_prompts", ["usage_count"])


def downgrade() -> None:
    op.drop_index("ix_style_prompts_usage_count", table_name="style_prompts")
    op.drop_column("style_prompts", "usage_count")
    op.drop_column("style_prompts", "is_new")