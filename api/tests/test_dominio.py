"""Guarda contra deriva entre os vocabulários Python e os CHECKs do banco.

`clima.dominio` e a migration 001 declaram a mesma lista de valores em dois
lugares. Se alguém adicionar um membro ao StrEnum e esquecer a migration, o
INSERT falha em produção — este teste falha antes.
"""

from __future__ import annotations

import re
from pathlib import Path

from clima.dominio import Redistribuicao, ResultadoColeta

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "001_fundacao.py"


def _valores_do_check(coluna: str) -> set[str]:
    fonte = MIGRATION.read_text(encoding="utf-8")
    m = re.search(rf"{coluna}\s+IN\s+\(([^)]*)\)", fonte)
    assert m, f"CHECK de {coluna} não encontrado na migration"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_redistribuicao_bate_com_o_check() -> None:
    assert {m.value for m in Redistribuicao} == _valores_do_check("redistribuicao")


def test_resultado_coleta_bate_com_o_check() -> None:
    assert {m.value for m in ResultadoColeta} == _valores_do_check("resultado")


def test_interna_e_o_padrao_seguro() -> None:
    """Copernicus e INMET precisam nascer 'interna'. Portão G4 do plano."""
    fonte = MIGRATION.read_text(encoding="utf-8")
    for sid in ("copernicus_ems", "inmet"):
        bloco = fonte[fonte.index(f'"id": "{sid}"') :][:400]
        assert '"redistribuicao": "interna"' in bloco, (
            f"{sid} deve nascer 'interna' até haver resposta jurídica por escrito"
        )
