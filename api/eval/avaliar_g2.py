"""Mede o portão G2: precisão ≥ 0,95 e recall ≥ 0,80 para terremotos.

    python eval/avaliar_g2.py

**Leia isto antes de acreditar no número.** O conjunto avaliado é misto, e as duas
metades têm status epistêmico diferente:

* **Negativos: reais.** Pares de sismos genuinamente distintos, extraídos de um
  payload real do USGS já coletado. O enxame da Califórnia produz os piores casos
  possíveis — eventos a poucos quilômetros e segundos de distância, dentro da janela
  de blocking. Precisão medida contra estes negativos significa algo.

* **Positivos: sintéticos.** O feed do USGS entrega eventos **já mesclados** — uma
  linha por evento, com `ids` listando as redes contribuintes. Não existe, no dado
  que temos, o mesmo sismo reportado duas vezes de forma independente. Então os
  positivos são perturbações do registro real, com deslocamentos calibrados pelas
  discrepâncias típicas entre agências sismológicas (epicentro ~5–25 km, horário de
  origem ~0,5–3 s, magnitude ~0,1–0,3).

Consequência: **o recall aqui vale só quanto valer o modelo de perturbação.** A
precisão é uma medida honesta; o recall é uma estimativa. O portão G2 só está
verdadeiramente atendido quando houver uma segunda fonte real — e é por isso que
este script imprime as duas coisas separadas em vez de um número único.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clima.correlation.features import (  # noqa: E402
    Parametros,
    Registro,
    extrair,
    score,
    veredito,
)

FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "usgs-all-hour.json"

SISMO = Parametros(
    event_type="earthquake",
    raio_m=100_000,
    janela_seg=90,
    peso_espaco=-4.0,
    peso_tempo=-5.5,
    peso_metrica=-3.0,
    peso_toponimo=0.8,
    intercepto=5.2,
    limiar_uniao=0.90,
    limiar_duvida=0.60,
    diametro_max_m=150_000,
    diametro_max_seg=120,
)

# Discrepâncias típicas entre agências para o mesmo sismo. Faixas conservadoras:
# se erram, erram para o lado de exigir mais do motor.
DESLOC_KM = (5.0, 25.0)
DESLOC_SEG = (0.5, 3.0)
DESLOC_MAG = (0.1, 0.3)

GRAU_KM = 111.32

# Abaixo disto, precisão não é medição — é ruído com aparência de resultado.
# Precisão sobre 1 negativo dá 1,0 ou 0,0, e nenhum dos dois informa nada. 30 é o
# piso grosseiro para o intervalo de confiança deixar de ser mais largo que a
# própria métrica.
MIN_NEGATIVOS = 30


@dataclass
class Par:
    a: Registro
    b: Registro
    mesmo: bool
    origem: str


def carregar_reais() -> list[Registro]:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    saida = []
    for i, f in enumerate(doc["features"]):
        p = f["properties"]
        c = f["geometry"]["coordinates"]
        saida.append(
            Registro(
                id=i + 1,
                source_id="usgs",
                source_event_id=f["id"],
                event_type="earthquake",
                lat=c[1],
                lon=c[0],
                observed_at=datetime.fromtimestamp(p["time"] / 1000, tz=UTC),
                magnitude=p.get("mag"),
                lugar=p.get("place"),
                status=p.get("status", "automatic"),
            )
        )
    return saida


def perturbar(r: Registro, rng: random.Random, id_: int) -> Registro:
    """Simula como uma segunda agência reportaria o MESMO sismo."""
    km = rng.uniform(*DESLOC_KM)
    rumo = rng.uniform(0, 6.283)
    import math

    return Registro(
        id=id_,
        source_id="emsc",
        source_event_id=f"emsc-{id_}",
        event_type="earthquake",
        lat=r.lat + (km / GRAU_KM) * math.cos(rumo),
        lon=r.lon + (km / (GRAU_KM * max(0.2, math.cos(math.radians(r.lat))))) * math.sin(rumo),
        observed_at=r.observed_at + timedelta(seconds=rng.uniform(*DESLOC_SEG)),
        magnitude=None
        if r.magnitude is None
        else round(r.magnitude + rng.choice([-1, 1]) * rng.uniform(*DESLOC_MAG), 2),
        # Topônimo de outra agência costuma ser redigido diferente. Não presentear
        # o motor com o mesmo texto: seria facilitar o próprio teste.
        lugar=None,
        status="automatic",
    )


def montar(seed: int = 7) -> list[Par]:
    rng = random.Random(seed)
    reais = carregar_reais()
    pares: list[Par] = []

    # Positivos sintéticos: cada real ganha uma "segunda agência".
    proximo = 1000
    for r in reais:
        for _ in range(3):
            proximo += 1
            pares.append(Par(r, perturbar(r, rng, proximo), True, "positivo_sintetico"))

    # Negativos reais: todos os pares distintos que o blocking geraria.
    for i, a in enumerate(reais):
        for b in reais[i + 1 :]:
            f = extrair(a, b, SISMO)
            if f.d_espaco < 1.0 and f.d_tempo < 1.0:
                pares.append(Par(a, b, False, "negativo_real"))

    return pares


def avaliar(pares: list[Par]) -> dict[str, object]:
    vp = fp = vn = fn = incertos_pos = incertos_neg = 0

    for par in pares:
        v = veredito(score(extrair(par.a, par.b, SISMO), SISMO), SISMO)
        if v == "incerto":
            # Incerto não é decisão: vai para revisão humana. Contado à parte, e
            # NÃO como acerto — inflar precisão com a fila de dúvida seria trapaça.
            if par.mesmo:
                incertos_pos += 1
            else:
                incertos_neg += 1
            continue
        if par.mesmo:
            vp += v == "mesmo"
            fn += v == "distinto"
        else:
            fp += v == "mesmo"
            vn += v == "distinto"

    precisao = vp / (vp + fp) if vp + fp else 1.0
    recall = vp / (vp + fn + incertos_pos) if vp + fn + incertos_pos else 0.0
    return {
        "positivos": sum(1 for p in pares if p.mesmo),
        "negativos": sum(1 for p in pares if not p.mesmo),
        "vp": vp,
        "fp": fp,
        "vn": vn,
        "fn": fn,
        "incertos_em_positivos": incertos_pos,
        "incertos_em_negativos": incertos_neg,
        "precisao": round(precisao, 4),
        "recall": round(recall, 4),
    }


def main() -> int:
    pares = montar()
    m = avaliar(pares)

    print("── Portão G2 — terremotos ─────────────────────────────────────────")
    print(f"positivos (SINTÉTICOS): {m['positivos']:>4}")
    print(f"negativos (REAIS):      {m['negativos']:>4}")
    print()
    print(f"verdadeiro positivo: {m['vp']:>4}    falso positivo: {m['fp']:>4}")
    print(f"verdadeiro negativo: {m['vn']:>4}    falso negativo: {m['fn']:>4}")
    print(f"incertos (revisão):  {m['incertos_em_positivos']} em positivos, "
          f"{m['incertos_em_negativos']} em negativos")
    print()
    print(f"PRECISÃO: {m['precisao']:.4f}   (mínimo G2: 0,95)  — medida contra negativo real")
    print(f"RECALL:   {m['recall']:.4f}   (mínimo G2: 0,80)  — estimado sobre positivo sintético")
    print()

    negativos = int(m["negativos"])  # type: ignore[call-overload]
    amostra_suficiente = negativos >= MIN_NEGATIVOS

    if not amostra_suficiente:
        print(f"AMOSTRA INSUFICIENTE: {negativos} negativo(s) reais, mínimo {MIN_NEGATIVOS}.")
        print(f"Precisão de {m['precisao']:.4f} sobre {negativos} caso(s) não é medição —")
        print("com essa amostra o valor só pode ser 1,0 ou 0,0, e nenhum dos dois")
        print("informa nada. Deixar o coletor rodando acumula negativos difíceis: um")
        print("dia de enxame na Califórnia rende dezenas de pares dentro da janela.")
        print("Regenere a fixture a partir de payloads coletados e rode de novo.")
        print()

    ok_prec = amostra_suficiente and m["precisao"] >= 0.95  # type: ignore[operator]
    ok_rec = m["recall"] >= 0.80  # type: ignore[operator]
    print(f"precisão: {'ATENDE' if ok_prec else 'NÃO VERIFICÁVEL AINDA'} · "
          f"recall: {'atende o limiar' if ok_rec else 'abaixo do limiar'} (sintético)")
    print()
    print("G2 NÃO está atendido, por dois motivos independentes: os positivos são")
    print("sintéticos (o USGS entrega eventos já mesclados) e a amostra de negativos")
    print("é pequena. Isto exercita o motor; não certifica o produto.")
    return 0 if (ok_prec and ok_rec) else 1


if __name__ == "__main__":
    raise SystemExit(main())
