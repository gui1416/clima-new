from __future__ import annotations

from datetime import date

import pytest

from clima.ingest.particoes import _add_meses


@pytest.mark.parametrize(
    ("origem", "n", "esperado"),
    [
        (date(2026, 8, 1), 0, date(2026, 8, 1)),
        (date(2026, 8, 1), 2, date(2026, 10, 1)),
        # A virada de ano é onde aritmética de mês costuma quebrar.
        (date(2026, 11, 1), 2, date(2027, 1, 1)),
        (date(2026, 12, 1), 1, date(2027, 1, 1)),
        (date(2026, 12, 1), 13, date(2028, 1, 1)),
    ],
)
def test_add_meses(origem: date, n: int, esperado: date) -> None:
    assert _add_meses(origem, n) == esperado
