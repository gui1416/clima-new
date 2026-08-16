from __future__ import annotations

import httpx

from clima.connectors.base import Validadores, resposta_de_httpx


def _resposta(status: int, headers: dict[str, str] | None = None, corpo: bytes = b"{}") -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        content=corpo,
        request=httpx.Request("GET", "https://exemplo.test/feed.geojson"),
    )


def test_sem_validadores_nao_manda_cabecalho_condicional() -> None:
    assert Validadores().cabecalhos() == {}


def test_validadores_viram_cabecalhos_condicionais() -> None:
    v = Validadores(etag='W/"abc"', last_modified="Sun, 16 Aug 2026 12:00:00 GMT")
    assert v.cabecalhos() == {
        "If-None-Match": 'W/"abc"',
        "If-Modified-Since": "Sun, 16 Aug 2026 12:00:00 GMT",
    }


def test_304_nao_traz_corpo() -> None:
    r = resposta_de_httpx(_resposta(304, {"etag": 'W/"abc"'}, corpo=b""))
    assert r.nao_modificado
    assert r.body is None
    assert r.validadores.etag == 'W/"abc"'


def test_200_traz_corpo_e_validadores() -> None:
    r = resposta_de_httpx(
        _resposta(200, {"etag": 'W/"xyz"', "content-type": "application/json"}, b'{"type":"F"}')
    )
    assert not r.nao_modificado
    assert r.body == b'{"type":"F"}'
    assert r.content_type == "application/json"
    assert r.validadores.etag == 'W/"xyz"'
