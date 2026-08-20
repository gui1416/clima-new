"""ativa GDACS e prepara conectores gratuitos validados

Revision ID: 008_fontes_gratuitas
Revises: 007_validacao_fontes
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op

revision = "008_fontes_gratuitas"
down_revision = "007_validacao_fontes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GDACS é terremoto e usa integralmente o contrato atual. O conector EONET já
    # existe, mas fica inativo enquanto a API só souber apresentar magnitude e
    # severidade sísmicas; ativá-lo antes disso rotularia acres como magnitude.
    op.execute("UPDATE sources SET ativa = true WHERE id = 'gdacs'")


def downgrade() -> None:
    op.execute("UPDATE sources SET ativa = false WHERE id = 'gdacs'")
