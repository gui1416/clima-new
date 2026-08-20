import { useEffect, useState } from "react";

import { Icone } from "../componentes/Icones";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "../componentes/ui/drawer";
import { detalharEvento } from "../dados/api";
import { ROTULO_SEVERIDADE, type EventoDetalhe, type EventoResumo } from "../tipos";
import { dataHora, instante, numero } from "../formato";

/** Valor de uma afirmação de fonte, em pt-BR.
 *
 * As afirmações chegam como JSON cru — é o que cada fonte publicou, sem
 * interpretação — e um `2026-08-20T20:48:41+00:00` no meio de uma coluna que
 * diz "3,4" e "10" é a única coisa na gaveta que não fala português. Formatar só
 * o que se reconhece com certeza; o resto passa como veio, que é o ponto de um
 * painel de procedência. */
const ISO_8601 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

function valorDeCampo(valor: unknown): string {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "number") return numero(valor, Number.isInteger(valor) ? 0 : 1);
  if (typeof valor === "string" && ISO_8601.test(valor)) {
    const d = new Date(valor);
    if (!Number.isNaN(d.getTime())) return dataHora(d);
  }
  return String(valor);
}

/**
 * Cartão do evento selecionado, com procedência.
 *
 * A procedência é a interface do diferencial do produto, e é honesta sobre o
 * estado dele: com uma fonte só, mostra uma fonte só e diz que não há
 * deduplicação. É o oposto de inventar consenso.
 */
export function CartaoEvento({
  evento,
  aoFechar,
}: {
  evento: EventoResumo;
  aoFechar: () => void;
}) {
  const [detalhe, setDetalhe] = useState<EventoDetalhe | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let vivo = true;
    setDetalhe(null);
    setErro(false);
    detalharEvento(evento.id)
      .then((d) => vivo && setDetalhe(d))
      .catch(() => vivo && setErro(true));
    return () => {
      vivo = false;
    };
  }, [evento.id]);

  return (
    <Drawer open onOpenChange={(aberto) => !aberto && aoFechar()} swipeDirection="right">
      <DrawerContent className="cartao-evento">
      <DrawerHeader>
        <div className="drawer-identidade">
          <span><i className={`ponto ${evento.severidade}`} />{ROTULO_SEVERIDADE[evento.severidade]} · sismo</span>
          <DrawerTitle>{evento.titulo}</DrawerTitle>
          <DrawerDescription>{evento.lugar ?? "Local não informado"} · {instante(evento.ocorrido_em)}</DrawerDescription>
        </div>
        <DrawerClose className="btn-icone" aria-label="Fechar detalhes">
          <Icone nome="close" tamanho="sm" />
        </DrawerClose>
      </DrawerHeader>

      <div className="cartao-evento-corpo">
      <p className="explicacao-evento">
        {evento.severidade === "critical"
          ? "Sismo de grande magnitude, destacado para atenção imediata."
          : evento.severidade === "high"
            ? "Magnitude relevante; impactos dependem da profundidade e da proximidade de áreas ocupadas."
            : "Evento monitorado, geralmente de menor potencial de impacto."}
      </p>

      {/* A métrica física nunca aparece sozinha nem escondida: severidade sem a
          grandeza que a originou é o erro que o produto existe para não cometer. */}
      <div className="metricas">
        <div className="metrica">
          <span>MAGNITUDE</span>
          <strong>{numero(evento.magnitude)}</strong>
        </div>
        <div className="metrica">
          <span>PROFUNDIDADE</span>
          <strong>{numero(evento.profundidade_km, 1)} km</strong>
        </div>
        <div className="metrica">
          <span>FONTES QUE CONFIRMAM</span>
          <strong>{evento.fontes_confirmando}</strong>
        </div>
        {/* Confiança nunca aparece sem a contagem de fontes ao lado: sozinha, um
            número de 0 a 1 parece medida física e não é. */}
        <div className="metrica">
          <span>CONFIANÇA</span>
          <strong>{Math.round(evento.confianca * 100)}%</strong>
        </div>
      </div>

      <div className="proc">
        <div className="proc-titulo">PROCEDÊNCIA</div>
        {erro ? (
          <p className="proc-nota erro-detalhe">Não foi possível carregar a procedência agora.</p>
        ) : detalhe ? (
          <>
            {detalhe.procedencia.map((p) => (
              <div className="proc-linha" key={p.fonte}>
                <strong>{p.nome}</strong>
                <span>{p.conteudo_restrito ? <em>licença restrita</em> : p.status}</span>
              </div>
            ))}

            {/* Campo por campo, o que cada fonte afirma. Com uma fonte não há
                divergência — e mostrar isso é honesto, não uma falha. */}
            {detalhe.campos.map((c) => (
              <div className={`proc-campo${c.divergente ? " divergente" : ""}`} key={c.campo}>
                <span>{c.campo}</span>
                <div>
                  {c.valores.map((v) => (
                    <b key={v.fonte} className={v.vencedor ? "adotado" : ""}>
                      {v.conteudo_restrito ? "—" : valorDeCampo(v.valor)}
                      <i>{v.fonte}</i>
                    </b>
                  ))}
                </div>
              </div>
            ))}

            <p className="proc-nota">
              {detalhe.fontes_confirmando > 1
                ? "Valor adotado em destaque; a precedência é por campo, nunca média entre fontes."
                : "Uma fonte confirma este evento. A divergência aparece quando duas ou mais o reportam."}
            </p>

            {/* O que cada fonte publicou, cru. É o último degrau antes do payload
                bruto — e é o degrau que permite conferir a síntese em vez de
                confiar nela. Fonte com licença restrita não chega até aqui: a API
                a remove de `metricas` na serialização. */}
            {Object.keys(detalhe.metricas).length > 0 && (
              <details className="metricas-fonte">
                <summary>Métricas cruas por fonte</summary>
                {Object.entries(detalhe.metricas).map(([fonte, valores]) => (
                  <div className="metricas-fonte-bloco" key={fonte}>
                    <span className="metricas-fonte-nome">{fonte}</span>
                    <dl>
                      {Object.entries(valores).map(([chave, valor]) => (
                        <div key={chave}>
                          <dt>{chave}</dt>
                          <dd>{valor === null || valor === undefined ? "—" : String(valor)}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ))}
              </details>
            )}
          </>
        ) : (
          <p className="proc-nota">carregando procedência…</p>
        )}
      </div>
      </div>
      </DrawerContent>
    </Drawer>
  );
}
