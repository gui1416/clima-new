import { useEffect, useState } from "react";

import { detalharEvento } from "../dados/api";
import { ROTULO_SEVERIDADE, type EventoDetalhe, type EventoResumo } from "../tipos";
import { instante, numero } from "../formato";

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

  useEffect(() => {
    let vivo = true;
    setDetalhe(null);
    detalharEvento(evento.id)
      .then((d) => vivo && setDetalhe(d))
      .catch(() => {});
    return () => {
      vivo = false;
    };
  }, [evento.id]);

  return (
    <aside className="flutuante cartao-evento" aria-label={`Detalhes de ${evento.titulo}`}>
      <header>
        <i className={`ponto ${evento.severidade}`} />
        {ROTULO_SEVERIDADE[evento.severidade]} · sismo
        <span className="espacador" />
        <button type="button" className="btn-icone" onClick={aoFechar} aria-label="Fechar">
          ×
        </button>
      </header>

      <h2>{evento.titulo}</h2>
      <p className="local">
        {evento.lugar ?? "local não informado"} · {instante(evento.ocorrido_em)}
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
        <div className="metrica">
          <span>REVISÕES DA FONTE</span>
          <strong>{evento.revisoes}</strong>
        </div>
      </div>

      <div className="proc">
        <div className="proc-titulo">PROCEDÊNCIA</div>
        {detalhe ? (
          <>
            {detalhe.procedencia.map((p) => (
              <div className="proc-linha" key={p.fonte}>
                <strong>{p.nome}</strong>
                <span>
                  {p.conteudo_restrito ? (
                    <em>conteúdo não redistribuível</em>
                  ) : (
                    <>
                      M {numero(p.magnitude)} · {p.status} · {p.revisoes} rev.
                    </>
                  )}
                </span>
              </div>
            ))}
            <p className="proc-nota">
              Uma fonte confirma este evento. Divergência entre fontes aparece aqui quando o
              motor de correlação existir — Fase 2.
            </p>
          </>
        ) : (
          <p className="proc-nota">carregando procedência…</p>
        )}
      </div>
    </aside>
  );
}
