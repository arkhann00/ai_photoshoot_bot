"""add promo_code_redemptions

Revision ID: 90eb263fb3fe
Revises: 3e9349f3816f
Create Date: 2025-12-22 02:27:49.166192

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90eb263fb3fe'
down_revision: Union[str, Sequence[str], None] = '3e9349f3816f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None




def upgrade() -> None:
    op.create_table(
        "promo_code_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "promo_code_id",
            sa.Integer(),
            sa.ForeignKey("promo_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "granted_generations",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "promo_code_id",
            "telegram_id",
            name="uq_promo_redemption",
        ),
    )

    op.create_index(
        "ix_promo_code_redemptions_promo_code_id",
        "promo_code_redemptions",
        ["promo_code_id"],
        unique=False,
    )
    op.create_index(
        "ix_promo_code_redemptions_telegram_id",
        "promo_code_redemptions",
        ["telegram_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_promo_code_redemptions_telegram_id",
        table_name="promo_code_redemptions",
    )
    op.drop_index(
        "ix_promo_code_redemptions_promo_code_id",
        table_name="promo_code_redemptions",
    )
    op.drop_table("promo_code_redemptions")
