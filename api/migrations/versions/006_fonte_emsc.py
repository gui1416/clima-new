"""emsc: a segunda fonte, para o motor de correlação ter trabalho real

Revision ID: 006_fonte_emsc
Revises: 005_correlacao
Create Date: 2026-08-16

O motor da Fase 2 existia sem nada para deduplicar: o feed do USGS entrega eventos
**já mesclados**, um por evento. O EMSC observa de forma independente, então o mesmo
terremoto passa a aparecer duas vezes com epicentro, horário e magnitude levemente
diferentes — que é o problema que o produto existe para resolver.

E não há atalho: o EMSC não carrega identificador do USGS. O cruzamento
determinístico do §5.2 não dispara entre as duas, então a decisão fica com o modelo
probabilístico. É o caso que valida o motor de verdade.

── Licença: `atribuicao` com CONFIRMAR pendente ──────────────────────────────

O seismicportal.eu é serviço público do EMSC e o dado é largamente reutilizado, mas
**não verifiquei os termos para redistribuição comercial**. Fica `atribuicao`, na
mesma condição do GDACS: usável na v1 gratuita, e o portão **G4** continua bloqueando
qualquer tier pago até haver resposta por escrito.

A alternativa era `interna`, que impediria a redistribuição por construção. Foi
descartada porque geraria evento visivelmente vazio quando só o EMSC reportasse um
sismo — o produto pareceria quebrado em vez de cauteloso, e o G4 já protege a receita.
"""

from __future__ import annotations

from alembic import op

revision = "006_fonte_emsc"
down_revision = "005_correlacao"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sources
          (id, nome, redistribuicao, atribuicao_exigida, intervalo_poll_seg, ativa, observacao)
        VALUES (
          'emsc',
          'EMSC — Centro Sismológico Euro-Mediterrâneo',
          'atribuicao',
          'Fonte: EMSC (seismicportal.eu)',
          -- O feed declara max-age de 15 s, mas 60 s casa com a cadência do resto do
          -- pipeline e é educado com um serviço público.
          60,
          true,
          'CONFIRMAR termos de redistribuição comercial antes do tier pago (G4). '
          'Sem identificador do USGS no payload: correlação é probabilística.'
        )
        ON CONFLICT (id) DO UPDATE
          SET ativa = true,
              redistribuicao = EXCLUDED.redistribuicao,
              atribuicao_exigida = EXCLUDED.atribuicao_exigida,
              observacao = EXCLUDED.observacao
        """
    )


def downgrade() -> None:
    op.execute("UPDATE sources SET ativa = false WHERE id = 'emsc'")
