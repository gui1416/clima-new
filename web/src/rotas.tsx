/** As telas, agora sobre dado real do back-end.
 *
 * O protótipo tinha seis rotas com dado de demonstração. Cinco delas existem aqui
 * com dado verdadeiro; "Relatórios" continua reservada, porque relatório sobre
 * dado não deduplicado repetiria o mesmo evento como se fossem vários — que é o
 * problema que o produto existe para resolver, não uma feature.
 */

import { useState } from "react";

import {
  buscarEstatisticas,
  buscarFontes,
  listarEventos,
  usePeriodico,
} from "./dados/api";
import { inteiro, instante, numero, relogio } from "./formato";
import { MapaGlobal } from "./mapa/MapaGlobal";
import { ROTULO_SEVERIDADE, SEVERIDADES, type Severidade } from "./tipos";

export interface Rota {
  caminho: string;
  rotulo: string;
  icone: string;
  grupo: "monitoramento" | "distribuicao";
  telaCheia?: boolean;
}

export const ROTAS: readonly Rota[] = [
  { caminho: "/visao-geral", rotulo: "Visão geral", icone: "▦", grupo: "monitoramento" },
  { caminho: "/mapa", rotulo: "Mapa global", icone: "◎", grupo: "monitoramento", telaCheia: true },
  { caminho: "/eventos", rotulo: "Eventos", icone: "≡", grupo: "monitoramento" },
  { caminho: "/fontes", rotulo: "Fontes de dados", icone: "◈", grupo: "monitoramento" },
  { caminho: "/alertas", rotulo: "Alertas & webhooks", icone: "△", grupo: "distribuicao" },
  { caminho: "/relatorios", rotulo: "Relatórios", icone: "▭", grupo: "distribuicao" },
] as const;

/** O aviso vem da API, não é redigido aqui: o back-end sabe quantos eventos têm mais
 *  de uma fonte, e a interface não deve estimar isso por conta própria. */
function AvisoDedup({ aviso }: { aviso: string | null }) {
  if (!aviso) return null;
  return (
    <p className="aviso-demo">
      <strong>Correlação ativa.</strong> {aviso}
    </p>
  );
}

export function TelaMapa() {
  return <MapaGlobal />;
}

// ── visão geral ────────────────────────────────────────────────────────────

export function TelaVisaoGeral() {
  const [horas, setHoras] = useState(24);
  const est = usePeriodico(() => buscarEstatisticas(horas, 0), [horas]);
  const recentes = usePeriodico(
    () => listarEventos({ horas, magnitudeMinima: 2.5, limite: 8 }),
    [horas],
  );
  const e = est.dado;

  return (
    <div className="pagina">
      <div className="cabecalho-pagina">
        <div className="chips" role="group" aria-label="Janela de tempo">
          {[6, 24, 72].map((h) => (
            <button
              key={h}
              type="button"
              aria-pressed={horas === h}
              onClick={() => setHoras(h)}
            >
              {h} h
            </button>
          ))}
        </div>
        <span className="atualizado">
          atualizado {relogio(est.atualizadoEm)} · a cada 60 s
        </span>
      </div>

      {recentes.dado && <AvisoDedup aviso={recentes.dado.aviso} />}

      <div className="painel-grid">
        <Painel titulo="SISMOS NA JANELA" valor={inteiro(e?.eventos_total)} nota={`${horas} h`} />
        <Painel
          titulo="MAGNITUDE MÁXIMA"
          valor={numero(e?.magnitude_maxima ?? null, 1)}
          nota="métrica física, não score"
        />
        <Painel
          titulo="ÚLTIMO EVENTO"
          valor={instante(e?.ultimo_evento_em ?? null)}
          nota="observado na fonte"
        />
        <Painel
          titulo="CONFIRMADOS POR 2+ FONTES"
          valor={inteiro(e?.eventos_multifonte)}
          nota={`${inteiro(e?.fontes_ativas)} fontes ativas`}
        />
      </div>

      <div className="duas-colunas">
        <section className="cartao">
          <h2>Por severidade</h2>
          {SEVERIDADES.map((s) => {
            const n = e?.por_severidade[s] ?? 0;
            const total = e?.eventos_total || 1;
            return (
              <div className="barra-linha" key={s}>
                <span>
                  <i className={`ponto ${s}`} /> {ROTULO_SEVERIDADE[s]}
                </span>
                <div className="barra">
                  <i className={s} style={{ width: `${(n / total) * 100}%` }} />
                </div>
                <b>{inteiro(n)}</b>
              </div>
            );
          })}
          <p className="nota">
            Faixas derivadas da magnitude: crítico ≥ 6,0, alto ≥ 4,5. É partição de uma grandeza
            física, não score composto entre categorias.
          </p>
        </section>

        <section className="cartao">
          <h2>Revisão da fonte</h2>
          {Object.entries(e?.por_status ?? {}).map(([status, n]) => (
            <div className="barra-linha" key={status}>
              <span>{status === "reviewed" ? "revisado por analista" : "automático"}</span>
              <div className="barra">
                <i
                  className={status === "reviewed" ? "moderate" : "high"}
                  style={{ width: `${(n / (e?.eventos_total || 1)) * 100}%` }}
                />
              </div>
              <b>{inteiro(n)}</b>
            </div>
          ))}
          <p className="nota">
            Solução automática vira revisada quando um analista confirma. É insumo de confiança —
            e o histórico guarda as duas versões.
          </p>
        </section>
      </div>

      <section className="cartao">
        <h2>Mais recentes</h2>
        <TabelaEventos itens={recentes.dado?.itens ?? []} compacta />
      </section>
    </div>
  );
}

function Painel({ titulo, valor, nota }: { titulo: string; valor: string; nota: string }) {
  return (
    <div className="painel">
      <span>{titulo}</span>
      <strong>{valor}</strong>
      <small>{nota}</small>
    </div>
  );
}

// ── eventos ────────────────────────────────────────────────────────────────

export function TelaEventos() {
  const [severidade, setSeveridade] = useState<Severidade | "">("");
  const [magMin, setMagMin] = useState(2.5);
  const pagina = usePeriodico(
    () => listarEventos({ horas: 72, magnitudeMinima: magMin, severidade, limite: 500 }),
    [severidade, magMin],
  );

  return (
    <div className="pagina">
      <div className="cabecalho-pagina">
        <div className="chips" role="group" aria-label="Filtrar por severidade">
          <button type="button" aria-pressed={severidade === ""} onClick={() => setSeveridade("")}>
            Todas
          </button>
          {SEVERIDADES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={severidade === s}
              onClick={() => setSeveridade(s)}
            >
              <i className={`ponto ${s}`} /> {ROTULO_SEVERIDADE[s]}
            </button>
          ))}
        </div>
        <label className="campo">
          magnitude mínima
          <input
            type="number"
            min={0}
            max={10}
            step={0.5}
            value={magMin}
            onChange={(ev) => setMagMin(Number(ev.target.value))}
          />
        </label>
        <span className="atualizado">
          {inteiro(pagina.dado?.total)} em 72 h · {relogio(pagina.atualizadoEm)}
        </span>
      </div>

      {pagina.dado && <AvisoDedup aviso={pagina.dado.aviso} />}
      {pagina.erro && <p className="aviso-erro">Falha ao atualizar: {pagina.erro}</p>}

      <TabelaEventos itens={pagina.dado?.itens ?? []} />
    </div>
  );
}

function TabelaEventos({
  itens,
  compacta = false,
}: {
  itens: import("./tipos").EventoResumo[];
  compacta?: boolean;
}) {
  if (!itens.length) {
    return <p className="nota">Nenhum registro na janela e nos filtros atuais.</p>;
  }
  return (
    <table className="tabela">
      <thead>
        <tr>
          <th>Evento</th>
          <th>Local</th>
          <th>Severidade</th>
          {/* Métrica ao lado da severidade, sempre. */}
          <th className="num">Magnitude</th>
          {!compacta && <th className="num">Profundidade</th>}
          {!compacta && <th className="num">Revisões</th>}
          <th className="num">Fontes</th>
          <th>Quando</th>
        </tr>
      </thead>
      <tbody>
        {itens.map((e) => (
          <tr key={e.id}>
            <td>{e.titulo}</td>
            <td>{e.lugar ?? "—"}</td>
            <td>
              <i className={`ponto ${e.severidade}`} /> {ROTULO_SEVERIDADE[e.severidade]}
            </td>
            <td className="num">
              <strong>{numero(e.magnitude, 1)}</strong>
            </td>
            {!compacta && <td className="num">{numero(e.profundidade_km, 1)} km</td>}
            {!compacta && <td className="num">{Math.round(e.confianca * 100)}%</td>}
            <td className="num">{e.fontes_confirmando}</td>
            <td>{instante(e.ocorrido_em)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── fontes ─────────────────────────────────────────────────────────────────

const ROTULO_LICENCA: Record<string, string> = {
  livre: "livre, inclusive comercial",
  atribuicao: "livre com atribuição",
  interna: "só uso interno — bloqueio G4",
};

export function TelaFontes() {
  const fontes = usePeriodico(buscarFontes);

  return (
    <div className="pagina">
      <div className="cabecalho-pagina">
        <span className="atualizado">atualizado {relogio(fontes.atualizadoEm)}</span>
      </div>

      <p className="aviso-demo">
        <strong>Licença é coluna no banco, não anotação.</strong> Fonte marcada como uso interno
        participa da correlação e da contagem de confiança, mas a API remove o conteúdo dela da
        resposta. Copernicus e INMET só saem desse estado com resposta jurídica por escrito.
      </p>

      <table className="tabela">
        <thead>
          <tr>
            <th>Fonte</th>
            <th>Estado</th>
            <th>Licença</th>
            <th className="num">Intervalo</th>
            <th>Última coleta</th>
            <th className="num">Erros 1 h</th>
          </tr>
        </thead>
        <tbody>
          {(fontes.dado ?? []).map((f) => (
            <tr key={f.source_id}>
              <td>{f.nome}</td>
              <td>
                <i className={`ponto ${f.ativa ? "" : "inativo"}`} />{" "}
                {f.ativa ? "coletando" : "catalogada, sem conector"}
              </td>
              <td className={f.redistribuicao === "interna" ? "restrito" : ""}>
                {ROTULO_LICENCA[f.redistribuicao] ?? f.redistribuicao}
              </td>
              <td className="num">{f.intervalo_poll_seg} s</td>
              <td>{instante(f.ultima_coleta_ok)}</td>
              <td className="num">{f.erros_1h}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── reservadas ─────────────────────────────────────────────────────────────

function Reservada({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div className="vazio">
      <h2>{titulo}</h2>
      <p>{texto}</p>
    </div>
  );
}

export function TelaAlertas() {
  return (
    <Reservada
      titulo="Alertas & webhooks"
      texto="Fora do escopo da v1 e dependente do portão G3: se o usuário gratuito primário for
        desenvolvedor, esta tela perde prioridade para o portal de API. Alertar sobre dado não
        deduplicado também dispararia o mesmo evento uma vez por fonte."
    />
  );
}

export function TelaRelatorios() {
  return (
    <Reservada
      titulo="Relatórios"
      texto="Reservada de propósito. Um relatório sobre dado não deduplicado contaria o mesmo
        evento como vários — exatamente o problema que o produto existe para resolver. Entra depois
        da Fase 2."
    />
  );
}
