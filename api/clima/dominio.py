"""Vocabulários do domínio. Espelham os CHECKs do banco — mudar aqui exige migration."""

from __future__ import annotations

from enum import StrEnum


class Redistribuicao(StrEnum):
    """Se o payload de uma fonte pode sair do sistema.

    É o mecanismo estrutural que impede redistribuição indevida. Fonte marcada
    ``INTERNA`` participa da correlação e do cálculo de confiança, mas seu
    conteúdo nunca é serializado numa resposta de API. Ver §6 do plano.
    """

    LIVRE = "livre"
    ATRIBUICAO = "atribuicao"
    INTERNA = "interna"


class ResultadoColeta(StrEnum):
    OK = "ok"
    NAO_MODIFICADO = "nao_modificado"  # HTTP 304: fonte respondeu, nada novo
    ERRO = "erro"


class TipoEvento(StrEnum):
    TERREMOTO = "terremoto"
    CICLONE = "ciclone"
    INCENDIO = "incendio"
    ENCHENTE = "enchente"
    VULCAO = "vulcao"
