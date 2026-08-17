"""validacao: registro de fontes com endpoint medido, não suposto

Revision ID: 007_validacao_fontes
Revises: 006_fonte_emsc
Create Date: 2026-08-17

As sete fontes foram sondadas de fato. O registro tinha intervalos de poll
inventados e nenhuma anotação de endpoint — o que significava que ativar uma fonte
exigia redescobrir a URL. Agora cada linha carrega o endpoint validado, se exige
chave, e quando foi verificada.

**Intervalo de poll agora vem do `cache-control` medido**, não de chute:

| Fonte        | cache-control medido        | intervalo adotado |
|--------------|-----------------------------|-------------------|
| USGS         | max-age=60                  | 60 s              |
| EMSC         | ausente (tem ETag)          | 60 s              |
| NOAA alertas | max-age=5                   | 300 s (educado)   |
| NOAA ciclone | max-age=300                 | 300 s             |
| GDACS        | ausente                     | 900 s             |
| INMET        | ausente                     | 600 s             |
| NASA EONET   | no-cache                    | 3600 s            |

── O achado que muda o portão G2 ─────────────────────────────────────────────

**O GDACS carrega o identificador do evento no USGS.** Cada evento traz
``source: "NEIC"`` e ``sourceid: "us6000tkcb"`` — em 100% dos 26 eventos da amostra.
NEIC é o centro do USGS.

Isso faz o cruzamento determinístico do §5.2 disparar entre GDACS e USGS, e — mais
importante — **dá verdade-base real e rotulada para o portão G2**: o GDACS afirma
quais dos seus eventos são quais eventos do USGS, então é possível medir se o caminho
probabilístico redescobre esses vínculos sem usar o xref. Era exatamente o que
faltava, e o EMSC não oferece (não traz id do USGS).

Ressalva: o GDACS só cobre eventos significativos. A amostra tinha magnitudes de 5,5
a 7,7. Então a verdade-base existe, e é limitada a essa faixa.

── O que NÃO foi validado ────────────────────────────────────────────────────

Isto foi validação **técnica** — alcançabilidade, formato, chave, cache. **Nenhuma
licença foi lida.** Os valores de ``redistribuicao`` seguem como estavam, e o portão
G4 continua bloqueando qualquer tier pago sobre fonte não confirmada por escrito.

O endpoint do Copernicus EMS **não foi localizado**: duas tentativas plausíveis
devolveram 404. Registrado como pendência real em vez de URL fictícia.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007_validacao_fontes"
down_revision = "006_fonte_emsc"
branch_labels = None
depends_on = None

# (id, endpoint, requer_chave, intervalo, ativa, observacao)
FONTES = [
    (
        "usgs",
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
        False,
        60,
        True,
        "Validado: 200, GeoJSON, Last-Modified (sem ETag), max-age=60. Entrega eventos "
        "JÁ MESCLADOS entre redes — properties.ids lista as contribuintes.",
    ),
    (
        "emsc",
        "https://www.seismicportal.eu/fdsnws/event/1/query?format=json",
        False,
        60,
        True,
        "Validado: 200, GeoJSON, ETag (sem Last-Modified). NÃO traz id do USGS, então a "
        "correlação com ele é só probabilística. Profundidade em properties.depth "
        "(positiva); coordinates[2] é elevação, sinal invertido em relação ao USGS.",
    ),
    (
        "gdacs",
        "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP?eventtype=EQ",
        False,
        900,
        False,
        "Validado: 200, GeoJSON, 26 eventos, ETag + Last-Modified. CARREGA O ID DO USGS "
        "em properties.sourceid com source='NEIC' (100% da amostra) — habilita "
        "cruzamento determinístico E verdade-base rotulada para o portão G2. Só cobre "
        "eventos significativos: amostra de M 5,5 a 7,7. Campo `glide` existe e veio "
        "vazio. Parâmetro é `eventtype` no singular.",
    ),
    (
        "noaa",
        "https://api.weather.gov/alerts/active",
        False,
        300,
        False,
        "Validado: 200, GeoJSON, 495 alertas ativos, 2,6 MB. max-age=5, mas 300 s é "
        "suficiente e educado. Rejeita o parâmetro `limit`. Ciclones ficam em endpoint "
        "separado: https://www.nhc.noaa.gov/CurrentStorms.json (200, ETag + "
        "Last-Modified, max-age=300). CAP tem `references`, que mapeia direto para "
        "snapshot append-only.",
    ),
    (
        "nasa_eonet",
        "https://eonet.gsfc.nasa.gov/api/v3/events?status=open",
        False,
        3600,
        False,
        "Validado: 200, objeto com events[], sem chave. Declara content-type "
        "application/rss+xml mas devolve JSON — não confie no cabeçalho. no-cache, sem "
        "ETag. Traz array de fontes com link ao boletim original: cruzamento de graça.",
    ),
    (
        "nasa_firms",
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_SNPP_NRT/world/1",
        True,
        900,
        False,
        "Validado: EXIGE MAP_KEY. Sem chave devolve 400 'Invalid MAP_KEY'. Registro "
        "gratuito em firms.modaps.eosdis.nasa.gov. Entrega pixels de foco, não eventos: "
        "exige clustering na ingestão (§5.6 do plano) antes de entrar no motor.",
    ),
    (
        "inmet",
        "https://apiprevmet3.inmet.gov.br/avisos/ativos",
        False,
        600,
        False,
        "Validado: 200, sem chave, 396 KB. Objeto com chaves `hoje` e `futuro`; 7 avisos "
        "hoje na amostra. Campos: descricao, aviso_cor, data_inicio/fim, estados, "
        "geocodes (municípios IBGE). Sem ETag nem cache-control.",
    ),
    (
        "copernicus_ems",
        None,
        False,
        3600,
        False,
        "NÃO VALIDADO: endpoint não localizado. /mapping/rss.xml e "
        "/mapping/list-of-activations-rapid devolveram 404. Precisa de investigação "
        "manual no portal antes de qualquer conector.",
    ),
]


def upgrade() -> None:
    op.execute("ALTER TABLE sources ADD COLUMN endpoint text")
    op.execute(
        "ALTER TABLE sources ADD COLUMN requer_chave boolean NOT NULL DEFAULT false"
    )
    # NULL = nunca sondada. Torna visível na tela de fontes o que é fato medido e o
    # que é suposição herdada.
    op.execute("ALTER TABLE sources ADD COLUMN validado_em timestamptz")

    # `sa.text(...).bindparams(...)`, e não um dict como segundo argumento de
    # `op.execute`: ali o segundo parâmetro é `execution_options`. Passar valores
    # ali levanta TypeError — foi o que derrubou o serviço migrate na primeira
    # tentativa, e o modo de falha mais gentil possível para esse erro.
    for sid, endpoint, chave, intervalo, ativa, obs in FONTES:
        op.execute(
            sa.text(
                """
                UPDATE sources
                   SET endpoint = :endpoint,
                       requer_chave = :chave,
                       intervalo_poll_seg = :intervalo,
                       ativa = :ativa,
                       observacao = :obs,
                       validado_em = now()
                 WHERE id = :sid
                """
            ).bindparams(
                endpoint=endpoint, chave=chave, intervalo=intervalo,
                ativa=ativa, obs=obs, sid=sid,
            )
        )

    # Copernicus não foi validado: a marca de validação fica nula, de propósito.
    op.execute("UPDATE sources SET validado_em = NULL WHERE id = 'copernicus_ems'")

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clima_app') THEN
            EXECUTE 'GRANT SELECT ON sources TO clima_app';
          END IF;
        END $$
        """
    )

    # DROP + CREATE, não CREATE OR REPLACE: o replace só aceita acrescentar coluna
    # no fim, e inserir no meio conta como renomear ("cannot change name of view
    # column"). O GRANT se perde no drop e é refeito abaixo.
    op.execute("DROP VIEW IF EXISTS v_saude_fontes")
    op.execute(
        """
        CREATE VIEW v_saude_fontes WITH (security_invoker = true) AS
        SELECT s.id AS source_id, s.nome, s.ativa, s.redistribuicao,
               s.intervalo_poll_seg, s.endpoint, s.requer_chave, s.validado_em,
               s.observacao,
               max(r.started_at) FILTER (WHERE r.resultado IN ('ok','nao_modificado'))
                 AS ultima_coleta_ok,
               max(r.started_at) FILTER (WHERE r.resultado = 'erro') AS ultimo_erro_em,
               count(*) FILTER (WHERE r.resultado = 'erro'
                                AND r.started_at > now() - interval '1 hour')
                 AS erros_1h
        FROM sources s
        LEFT JOIN ingest_runs r ON r.source_id = s.id
        GROUP BY s.id, s.nome, s.ativa, s.redistribuicao, s.intervalo_poll_seg,
                 s.endpoint, s.requer_chave, s.validado_em, s.observacao
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clima_app') THEN
            EXECUTE 'GRANT SELECT ON v_saude_fontes TO clima_app';
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_saude_fontes")
    op.execute(
        """
        CREATE VIEW v_saude_fontes WITH (security_invoker = true) AS
        SELECT s.id AS source_id, s.nome, s.ativa, s.redistribuicao,
               s.intervalo_poll_seg,
               max(r.started_at) FILTER (WHERE r.resultado IN ('ok','nao_modificado'))
                 AS ultima_coleta_ok,
               max(r.started_at) FILTER (WHERE r.resultado = 'erro') AS ultimo_erro_em,
               count(*) FILTER (WHERE r.resultado = 'erro'
                                AND r.started_at > now() - interval '1 hour')
                 AS erros_1h
        FROM sources s
        LEFT JOIN ingest_runs r ON r.source_id = s.id
        GROUP BY s.id, s.nome, s.ativa, s.redistribuicao, s.intervalo_poll_seg
        """
    )
    for c in ("validado_em", "requer_chave", "endpoint"):
        op.execute(f"ALTER TABLE sources DROP COLUMN IF EXISTS {c}")
