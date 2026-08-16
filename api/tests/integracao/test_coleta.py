"""O coletor de ponta a ponta, sem rede.

Um conector falso substitui o do USGS. Testar contra a fonte real deixaria a
suíte dependente de disponibilidade de terceiro e de conexão — e não provaria
nada a mais sobre o nosso código.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from clima.connectors.base import Resposta, Validadores
from clima.dominio import ResultadoColeta
from clima.ingest.continuidade import lacunas, silenciosas
from clima.ingest.runner import coletar_fonte

CORPO = b'{"type":"FeatureCollection","features":[]}'
SHA = hashlib.sha256(CORPO).digest()


class ConectorFalso:
    """Devolve respostas roteirizadas e registra os validadores que recebeu."""

    id = "usgs"

    def __init__(self, *respostas: Resposta | Exception) -> None:
        self.roteiro = list(respostas)
        self.recebidos: list[Validadores] = []

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        self.recebidos.append(anteriores)
        proxima = self.roteiro.pop(0) if self.roteiro else _ok()
        if isinstance(proxima, Exception):
            raise proxima
        return proxima


def _ok(corpo: bytes = CORPO, etag: str | None = 'W/"v1"') -> Resposta:
    return Resposta(
        url="https://exemplo.test/all_hour.geojson",
        http_status=200,
        headers={"etag": etag} if etag else {},
        body=corpo,
        content_type="application/json",
        validadores=Validadores(etag=etag),
    )


def _nao_modificado() -> Resposta:
    return Resposta(
        url="https://exemplo.test/all_hour.geojson",
        http_status=304,
        body=None,
        validadores=Validadores(etag='W/"v1"'),
    )


@pytest.fixture
def instalar(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    def _instalar(fake: ConectorFalso) -> ConectorFalso:
        monkeypatch.setattr("clima.ingest.runner.conector", lambda _sid: fake)
        return fake

    return _instalar


async def _contar(dono: AsyncEngine) -> tuple[int, int, int]:
    async with dono.connect() as c:
        return (
            (await c.execute(text("SELECT count(*) FROM ingest_runs"))).scalar_one(),
            (await c.execute(text("SELECT count(*) FROM payload_bodies"))).scalar_one(),
            (await c.execute(text("SELECT count(*) FROM raw_payloads"))).scalar_one(),
        )


async def test_coleta_grava_o_bruto(dono: AsyncEngine, instalar) -> None:  # noqa: ANN001
    instalar(ConectorFalso(_ok()))

    assert await coletar_fonte("usgs") == ResultadoColeta.OK

    runs, corpos, coletas = await _contar(dono)
    assert (runs, corpos, coletas) == (1, 1, 1)

    async with dono.connect() as c:
        sha, corpo = (
            await c.execute(text("SELECT sha256, body FROM payload_bodies"))
        ).one()
        resultado, etag = (
            await c.execute(text("SELECT resultado, etag FROM ingest_runs"))
        ).one()

    assert bytes(sha) == SHA
    assert bytes(corpo) == CORPO  # byte a byte, é o ponto de payload_raw
    assert resultado == "ok"
    assert etag == 'W/"v1"'


async def test_corpo_repetido_registra_coleta_sem_duplicar_corpo(
    dono: AsyncEngine, instalar
) -> None:  # noqa: ANN001
    instalar(ConectorFalso(_ok(), _ok()))

    await coletar_fonte("usgs")
    await coletar_fonte("usgs")

    runs, corpos, coletas = await _contar(dono)
    assert corpos == 1, "corpo idêntico não deve ocupar duas linhas"
    assert coletas == 2, "cada coleta precisa ficar registrada — é o que prova continuidade"
    assert runs == 2


async def test_304_nao_grava_coleta(dono: AsyncEngine, instalar) -> None:  # noqa: ANN001
    instalar(ConectorFalso(_ok(), _nao_modificado()))

    await coletar_fonte("usgs")
    assert await coletar_fonte("usgs") == ResultadoColeta.NAO_MODIFICADO

    _, corpos, coletas = await _contar(dono)
    assert (corpos, coletas) == (1, 1)

    async with dono.connect() as c:
        resultados = list(
            (
                await c.execute(text("SELECT resultado FROM ingest_runs ORDER BY id"))
            ).scalars()
        )
    assert resultados == ["ok", "nao_modificado"]


async def test_validador_vem_da_ultima_coleta_com_corpo(instalar) -> None:  # noqa: ANN001
    """Depois de um 304, a próxima requisição ainda manda o ETag do último OK.

    Herdar o validador do 304 desligaria a requisição condicional para sempre.
    """
    fake = instalar(ConectorFalso(_ok(), _nao_modificado(), _nao_modificado()))

    await coletar_fonte("usgs")
    await coletar_fonte("usgs")
    await coletar_fonte("usgs")

    assert fake.recebidos[0].etag is None  # primeira coleta, sem histórico
    assert fake.recebidos[1].etag == 'W/"v1"'
    assert fake.recebidos[2].etag == 'W/"v1"'


async def test_falha_de_rede_registra_run_com_erro(dono: AsyncEngine, instalar) -> None:  # noqa: ANN001
    instalar(ConectorFalso(httpx.ConnectError("sem rota")))

    assert await coletar_fonte("usgs") == ResultadoColeta.ERRO

    runs, corpos, coletas = await _contar(dono)
    assert (runs, corpos, coletas) == (1, 0, 0)

    async with dono.connect() as c:
        resultado, erro, fim = (
            await c.execute(text("SELECT resultado, erro, finished_at FROM ingest_runs"))
        ).one()
    assert resultado == "erro"
    assert "ConnectError" in erro
    assert fim is not None, "run precisa ser fechado mesmo em falha, senão vira lacuna fantasma"


async def test_coleta_alimenta_a_saude_da_fonte(dono: AsyncEngine, instalar) -> None:  # noqa: ANN001
    """A cascata que importa: se o run não é fechado, `resultado` fica NULL e as
    três coisas que filtram por ele mentem juntas — saúde da fonte, detecção de
    lacuna e requisição condicional. O dado bruto continua correto, e a
    instrumentação que deveria provar isso é que quebra."""
    instalar(ConectorFalso(_ok()))
    await coletar_fonte("usgs")

    async with dono.connect() as c:
        ultima_ok, erros = (
            await c.execute(
                text(
                    "SELECT ultima_coleta_ok, erros_1h FROM v_saude_fontes WHERE source_id = 'usgs'"
                )
            )
        ).one()

    assert ultima_ok is not None, "coleta bem-sucedida não apareceu em v_saude_fontes"
    assert erros == 0

    # A fonte que acabou de coletar não pode constar como silenciosa. O EMSC
    # aparece, e corretamente: neste banco de teste ele nunca coletou.
    assert "usgs" not in [s.source_id for s in await silenciosas()]


async def test_lacuna_e_detectada(dono: AsyncEngine) -> None:
    """Duas coletas separadas por 20 min viram lacuna acima do limite de 5 min."""
    async with dono.begin() as c:
        await c.execute(
            text(
                """
                INSERT INTO ingest_runs (tenant_id, source_id, started_at, resultado)
                VALUES (clima_system_tenant(), 'usgs', now() - interval '25 minutes', 'ok'),
                       (clima_system_tenant(), 'usgs', now() - interval '5 minutes',  'ok')
                """
            )
        )

    encontradas = await lacunas()
    assert len(encontradas) == 1
    assert encontradas[0].source_id == "usgs"
    assert 19 * 60 < encontradas[0].duracao.total_seconds() < 21 * 60
