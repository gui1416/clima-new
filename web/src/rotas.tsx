/** As telas, agora sobre dado real do back-end.
 *
 * O protótipo tinha seis rotas com dado de demonstração. Cinco delas existem aqui
 * com dado verdadeiro; "Relatórios" continua reservada, porque relatório sobre
 * dado não deduplicado repetiria o mesmo evento como se fossem vários — que é o
 * problema que o produto existe para resolver, não uma feature.
 *
 * A gramática visual é a do protótipo: selo + linha de contexto + título grande,
 * cartão de indicador com selo de destaque, feed lateral. O que mudou em relação
 * a ele é a procedência dos números — todos vêm da API, nenhum é escrito à mão.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Icone, type NomeIcone } from "./componentes/Icones";
import {
  buscarEstatisticas,
  buscarFontes,
  buscarSaude,
  listarEventos,
  useFluxoDeEventos,
  usePeriodico,
} from "./dados/api";
import { inteiro, instante, numero, relogio } from "./formato";
import { MapaGlobal } from "./mapa/MapaGlobal";
import {
  ROTULO_SEVERIDADE,
  SEVERIDADES,
  type EventoResumo,
  type SaudeFonte,
  type Severidade,
} from "./tipos";

export interface Rota {
  caminho: string;
  rotulo: string;
  icone: NomeIcone;
  grupo: "monitoramento" | "distribuicao";
  telaCheia?: boolean;
}

export const ROTAS: readonly Rota[] = [
  { caminho: "/visao-geral", rotulo: "Visão geral", icone: "grid", grupo: "monitoramento" },
  { caminho: "/mapa", rotulo: "Mapa global", icone: "globe", grupo: "monitoramento", telaCheia: true },
  { caminho: "/eventos", rotulo: "Eventos", icone: "activity", grupo: "monitoramento" },
  { caminho: "/fontes", rotulo: "Fontes de dados", icone: "db", grupo: "monitoramento" },
  { caminho: "/alertas", rotulo: "Alertas & webhooks", icone: "bell", grupo: "distribuicao" },
  { caminho: "/relatorios", rotulo: "Relatórios", icone: "file", grupo: "distribuicao" },
] as const;

/** Cabeçalho de tela do protótipo: selo, linha de contexto, título, ação. */
function CabecalhoTela({
  selo,
  contexto,
  titulo,
  descricao,
  acao,
}: {
  selo: string;
  contexto?: React.ReactNode;
  titulo: string;
  descricao: string;
  acao?: React.ReactNode;
}) {
  return (
    <header className="cabecalho-tela">
      <div className="cabecalho-tela-copy">
        <div className="linha-selo">
          <span className="selo-tela">{selo}</span>
          {contexto && <span className="contexto-tela">{contexto}</span>}
        </div>
        <h2>{titulo}</h2>
        <p>{descricao}</p>
      </div>
      {acao}
    </header>
  );
}

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
  const fluxo = useFluxoDeEventos();
  const est = usePeriodico(() => buscarEstatisticas(horas, 0), [horas, fluxo.revisao]);
  const recentes = usePeriodico(
    () => listarEventos({ horas, magnitudeMinima: 2.5, limite: 8 }),
    [horas, fluxo.revisao],
  );
  const feed = usePeriodico(
    () => listarEventos({ horas, magnitudeMinima: 0, limite: 7 }),
    [horas, fluxo.revisao],
  );
  const e = est.dado;
  const percentualMultifonte =
    e && e.eventos_total ? Math.round((e.eventos_multifonte / e.eventos_total) * 100) : 0;

  return (
    <div className="pagina">
      <CabecalhoTela
        selo="MONITORAMENTO GLOBAL"
        contexto={
          <>
            {inteiro(e?.eventos_total)} eventos em {horas} h · atualizado{" "}
            {relogio(est.atualizadoEm)}
          </>
        }
        titulo="O que exige atenção agora"
        descricao="Eventos sísmicos consolidados entre as fontes ativas, sem esconder divergências."
        acao={
          <Link to="/mapa" className="acao-principal">
            <Icone nome="globe" tamanho="sm" />
            Abrir mapa global
          </Link>
        }
      />

      <div className="cabecalho-pagina">
        <div className="chips" role="group" aria-label="Janela de tempo">
          {[6, 24, 72].map((h) => (
            <button key={h} type="button" aria-pressed={horas === h} onClick={() => setHoras(h)}>
              {h} h
            </button>
          ))}
        </div>
        <span className="atualizado">
          {fluxo.estado === "ao-vivo" ? "fluxo ao vivo" : "revalidação a cada 60 s"}
        </span>
      </div>

      {/* Do mesmo `est` que alimenta os painéis: o aviso e os números precisam
          responder à mesma pergunta com o mesmo filtro. */}
      {e && <AvisoDedup aviso={e.aviso} />}

      <div className="painel-grid">
        <Painel
          titulo="SISMOS NA JANELA"
          valor={inteiro(e?.eventos_total)}
          destaque={`${horas} H`}
          nota="tudo que entrou pela coleta"
        />
        <Painel
          titulo="MAGNITUDE MÁXIMA"
          valor={numero(e?.magnitude_maxima ?? null, 1)}
          destaque="FÍSICA"
          papel="ok"
          nota="grandeza medida, não score"
        />
        <Painel
          titulo="ÚLTIMO EVENTO"
          valor={instante(e?.ultimo_evento_em ?? null)}
          nota="horário observado na fonte"
        />
        <Painel
          titulo="CONFIRMADOS POR 2+ FONTES"
          valor={inteiro(e?.eventos_multifonte)}
          // Percentual derivado dos dois números que já estão na tela — não é
          // tendência inventada, é a razão entre eles.
          destaque={`${percentualMultifonte}%`}
          papel={percentualMultifonte > 0 ? "ok" : "atencao"}
          nota={`${inteiro(e?.fontes_ativas)} fontes ativas`}
        />
      </div>

      <div className="grade-visao">
        <div className="coluna-visao">
          <div className="duas-colunas">
            <section className="cartao">
              <h2>Confirmação entre fontes</h2>
              {/* A métrica do diferencial, em rampa ORDINAL de uma matiz: mais fontes =
                  passo mais escuro (invertido no tema escuro). Ordinal e não categórica
                  porque trocar a ordem mudaria o significado. */}
              <ConfirmacaoEntreFontes
                total={e?.eventos_total ?? 0}
                multifonte={e?.eventos_multifonte ?? 0}
              />
              <p className="nota">
                O GDACS confirma sismos significativos pelo identificador USGS; o EMSC oferece uma
                observação independente. Fonte única continua visível como fonte única.
              </p>
            </section>

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
          </div>

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

        <FeedAoVivo eventos={feed.dado?.itens ?? []} aoVivo={fluxo.estado === "ao-vivo"} />
      </div>

      <section className="cartao">
        <h2>Mais recentes</h2>
        {/* Recorte diferente dos painéis, e o rótulo diz qual — a tabela mostra o
            que é operacionalmente relevante, não a contagem total. */}
        <p className="nota" style={{ margin: "0 0 12px" }}>
          Acima de M 2,5, os oito mais recentes. Os painéis acima contam todos.
        </p>
        <TabelaEventos itens={recentes.dado?.itens ?? []} compacta />
      </section>
    </div>
  );
}

/** Feed lateral do protótipo, sobre a lista real e sem piso de magnitude.
 *
 * O piso zero é deliberado: os painéis contam a janela inteira, e um feed que
 * silenciasse o microssismo estaria descrevendo outra população que a do número
 * ao lado. O rótulo diz o recorte. */
function FeedAoVivo({ eventos, aoVivo }: { eventos: EventoResumo[]; aoVivo: boolean }) {
  const navegar = useNavigate();
  return (
    <section className="cartao feed" aria-label="Últimos eventos recebidos">
      <header className="feed-cabecalho">
        <div>
          <span className="sobretitulo">ATUALIZAÇÕES</span>
          <h2>Feed de eventos</h2>
        </div>
        <span className={`selo-fluxo${aoVivo ? " ativo" : ""}`}>
          <i /> {aoVivo ? "AO VIVO" : "60 S"}
        </span>
      </header>

      <div className="feed-lista">
        {eventos.map((e) => (
          <button
            key={e.id}
            type="button"
            className="feed-item"
            onClick={() => navegar(`/mapa?evento=${encodeURIComponent(e.id)}`)}
          >
            <span className="feed-topo">
              <span className={`rotulo-severidade ${e.severidade}`}>
                <i className={`ponto ${e.severidade}`} />
                {ROTULO_SEVERIDADE[e.severidade]}
              </span>
              <small>{instante(e.ocorrido_em)}</small>
            </span>
            <strong>{e.titulo}</strong>
            <small className="feed-lugar">{e.lugar ?? "Local não informado"}</small>
            <span className="feed-meta">
              {e.fontes.join(" + ")} ·{" "}
              {e.fontes_confirmando > 1 ? `${e.fontes_confirmando} fontes` : "fonte única"}
            </span>
            <Icone nome="chevron" tamanho="sm" className="feed-seta" />
          </button>
        ))}
        {!eventos.length && <p className="nota">Nenhum evento nesta janela.</p>}
      </div>

      <Link to="/eventos" className="feed-rodape">
        Ver todos os eventos <Icone nome="arrow" tamanho="sm" />
      </Link>
    </section>
  );
}

/** Medidor de duas faixas, com valor visível em cada uma.
 *
 * O rótulo numérico não é enfeite: no tema claro os passos claros da rampa ficam
 * abaixo de 3:1 sobre branco, e a mitigação exigida é exatamente o valor legível
 * ao lado. Texto em tinta de texto, nunca na cor da série.
 */
function ConfirmacaoEntreFontes({ total, multifonte }: { total: number; multifonte: number }) {
  const unica = Math.max(0, total - multifonte);
  const faixas = [
    { rotulo: "uma fonte", n: unica, passo: "ord-1" },
    { rotulo: "duas ou mais", n: multifonte, passo: "ord-3" },
  ];
  return (
    <>
      <div
        className="medidor"
        role="img"
        aria-label={`${unica} eventos com uma fonte, ${multifonte} com duas ou mais`}
      >
        {faixas.map((f) => (
          <i
            key={f.rotulo}
            className={f.passo}
            style={{ width: `${total ? (f.n / total) * 100 : 0}%` }}
            title={`${f.rotulo}: ${f.n}`}
          />
        ))}
      </div>
      {faixas.map((f) => (
        <div className="barra-linha" key={f.rotulo}>
          <span>
            <i className={`quadro ${f.passo}`} /> {f.rotulo}
          </span>
          <div className="barra">
            <i className={f.passo} style={{ width: `${total ? (f.n / total) * 100 : 0}%` }} />
          </div>
          <b>{inteiro(f.n)}</b>
        </div>
      ))}
    </>
  );
}

function Painel({
  titulo,
  valor,
  nota,
  destaque,
  papel = "neutro",
}: {
  titulo: string;
  valor: string;
  nota: string;
  destaque?: string;
  papel?: "neutro" | "ok" | "atencao";
}) {
  return (
    <div className="painel">
      <div className="painel-topo">
        <span>{titulo}</span>
        {destaque && <em className={`painel-selo selo-${papel}`}>{destaque}</em>}
      </div>
      <strong>{valor}</strong>
      <small>{nota}</small>
    </div>
  );
}

// ── eventos ────────────────────────────────────────────────────────────────

const PAGINA = 60;

export function TelaEventos() {
  const [severidade, setSeveridade] = useState<Severidade | "">("");
  const [magMin, setMagMin] = useState(2.5);
  // O filtro do diferencial. `fontes_minimas=2` existe na API desde a Fase 3 e
  // não tinha interface: é a única consulta que responde "o que o motor de
  // correlação de fato uniu", e era a que não dava para fazer pela tela.
  const [soMultifonte, setSoMultifonte] = useState(false);
  const [extras, setExtras] = useState<EventoResumo[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [carregandoMais, setCarregandoMais] = useState(false);
  const fluxo = useFluxoDeEventos();

  const filtro = {
    horas: 72,
    magnitudeMinima: magMin,
    severidade,
    fontesMinimas: soMultifonte ? 2 : 0,
    limite: PAGINA,
  };

  const pagina = usePeriodico(
    () => listarEventos(filtro),
    [severidade, magMin, soMultifonte, fluxo.revisao],
  );

  // Trocar filtro invalida o que já foi paginado: as páginas seguintes foram
  // colhidas sob outro predicado e misturá-las produziria uma lista que nenhuma
  // consulta devolveria.
  useEffect(() => {
    setExtras([]);
    setCursor(null);
  }, [severidade, magMin, soMultifonte]);

  const proximo = cursor ?? pagina.dado?.proximo_cursor ?? null;

  async function carregarMais() {
    if (!proximo || carregandoMais) return;
    setCarregandoMais(true);
    try {
      const p = await listarEventos({ ...filtro, cursor: proximo });
      setExtras((a) => [...a, ...p.itens]);
      setCursor(p.proximo_cursor);
    } catch {
      // Silencioso de propósito: a lista já exibida continua válida, e o botão
      // segue disponível para nova tentativa.
    } finally {
      setCarregandoMais(false);
    }
  }

  // A primeira página é revalidada a cada delta; as seguintes, não. Sem a
  // deduplicação por id, um evento que entrasse no topo apareceria duas vezes.
  const itens = useMemo(() => {
    const porId = new Map<string, EventoResumo>();
    for (const e of [...(pagina.dado?.itens ?? []), ...extras]) porId.set(e.id, e);
    return [...porId.values()];
  }, [pagina.dado, extras]);

  return (
    <div className="pagina">
      <CabecalhoTela
        selo="CATÁLOGO CANÔNICO"
        contexto={
          <>
            {inteiro(pagina.dado?.total)} eventos em 72 h · {itens.length} carregados
          </>
        }
        titulo="Eventos observados"
        descricao="Um evento por fenômeno, com magnitude física, procedência e confiança da consolidação."
        acao={
          <button
            type="button"
            className={`acao-principal${soMultifonte ? " ativa" : ""}`}
            aria-pressed={soMultifonte}
            onClick={() => setSoMultifonte((v) => !v)}
          >
            <Icone nome={soMultifonte ? "check" : "filter"} tamanho="sm" />
            Só confirmados por 2+ fontes
          </button>
        }
      />

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
        <span className="atualizado">{relogio(pagina.atualizadoEm)}</span>
      </div>

      {pagina.dado && <AvisoDedup aviso={pagina.dado.aviso} />}
      {pagina.erro && <p className="aviso-erro">Falha ao atualizar: {pagina.erro}</p>}

      {pagina.carregando && !pagina.dado ? (
        <EstadoCarregando texto="Buscando eventos nas fontes ativas…" />
      ) : (
        <>
          <TabelaEventos itens={itens} />
          {proximo && (
            <button type="button" className="carregar-mais" onClick={carregarMais} disabled={carregandoMais}>
              {carregandoMais ? "Carregando…" : `Carregar mais ${PAGINA}`}
              <Icone nome="chevron" tamanho="sm" />
            </button>
          )}
        </>
      )}
    </div>
  );
}

function TabelaEventos({
  itens,
  compacta = false,
}: {
  itens: EventoResumo[];
  compacta?: boolean;
}) {
  const navegar = useNavigate();
  if (!itens.length) {
    return <p className="nota">Nenhum registro na janela e nos filtros atuais.</p>;
  }
  return (
    // O invólucro rolável é o que impede a tabela de empurrar a página inteira
    // na faixa de tablet, onde as sete colunas ainda não viram cartão.
    <div className="tabela-rolagem">
      <table className={`tabela${compacta ? " tabela-compacta" : ""}`}>
        <thead>
          <tr>
            <th>Evento</th>
            <th>Local</th>
            <th>Severidade</th>
            {/* Métrica ao lado da severidade, sempre. */}
            <th className="num">Magnitude</th>
            {!compacta && <th className="num">Profundidade</th>}
            {!compacta && <th className="num">Confiança</th>}
            <th className="num">Fontes</th>
            <th>Quando</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((e) => (
            <tr
              key={e.id}
              tabIndex={0}
              role="link"
              onClick={() => navegar(`/mapa?evento=${encodeURIComponent(e.id)}`)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter") navegar(`/mapa?evento=${encodeURIComponent(e.id)}`);
              }}
            >
              <td data-label="Evento">
                <strong className="evento-nome">{e.titulo}</strong>
                <span className="evento-id">{e.fontes.join(" + ")}</span>
              </td>
              <td data-label="Local">{e.lugar ?? "local não informado"}</td>
              <td data-label="Severidade">
                <span className={`selo-severidade ${e.severidade}`}>
                  <i className={`ponto ${e.severidade}`} /> {ROTULO_SEVERIDADE[e.severidade]}
                </span>
              </td>
              <td className="num" data-label="Magnitude">
                <strong>{numero(e.magnitude, 1)}</strong>
              </td>
              {!compacta && (
                <td className="num" data-label="Profundidade">
                  {numero(e.profundidade_km, 1)} km
                </td>
              )}
              {!compacta && (
                <td className="num" data-label="Confiança">
                  {Math.round(e.confianca * 100)}%
                </td>
              )}
              <td className="num" data-label="Fontes">
                {e.fontes_confirmando}
              </td>
              <td data-label="Quando">{instante(e.ocorrido_em)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── fontes ────────────────────────────────────────────────────────────────

/** Estado de uma fonte, derivado dos fatos e não digitado à mão.
 *
 * Escala de STATUS: papéis reservados, e a cor **nunca** carrega o significado
 * sozinha — sempre com símbolo e rótulo. Sem isso, um leitor com deuteranopia lê
 * "coletando" e "bloqueada" como a mesma coisa.
 */
function estadoDaFonte(f: SaudeFonte): { papel: string; simbolo: string; rotulo: string } {
  if (f.ativa && f.erros_1h > 0) return { papel: "atencao", simbolo: "▲", rotulo: "coletando com erros" };
  if (f.ativa) return { papel: "ok", simbolo: "●", rotulo: "coletando" };
  // `validado_em` nulo vem ANTES da licença: não saber a URL é obstáculo mais
  // fundamental que não poder redistribuir. O Copernicus tem os dois problemas, e
  // mostrar o menos básico esconderia o que de fato bloqueia o próximo passo.
  if (!f.validado_em) return { papel: "bloqueado", simbolo: "■", rotulo: "endpoint não localizado" };
  if (f.redistribuicao === "interna") return { papel: "bloqueado", simbolo: "■", rotulo: "licença bloqueia" };
  if (f.requer_chave) return { papel: "atencao", simbolo: "▲", rotulo: "exige chave" };
  return { papel: "inerte", simbolo: "○", rotulo: "validada, sem conector" };
}

const ROTULO_LICENCA: Record<string, string> = {
  livre: "livre, inclusive comercial",
  atribuicao: "livre com atribuição",
  interna: "só uso interno",
};

/** Cadência como medidor de trilho, não como número solto.
 *
 * Os intervalos vão de 60 s a 3600 s — 60× de amplitude. Escala logarítmica,
 * porque em linear tudo abaixo de 600 s viraria um traço indistinguível.
 */
function Cadencia({ segundos }: { segundos: number }) {
  const fracao = Math.log(segundos / 60) / Math.log(3600 / 60);
  const texto = segundos >= 3600 ? `${segundos / 3600} h` : segundos >= 60 ? `${segundos / 60} min` : `${segundos} s`;
  return (
    <span className="cadencia" title={`${segundos} s entre coletas`}>
      <i style={{ width: `${Math.max(6, fracao * 100)}%` }} />
      <b>{texto}</b>
    </span>
  );
}

/** Integridade da coleta, de `/saude`.
 *
 * A tela de fontes descrevia cada integração isoladamente e não dizia se o
 * conjunto está de pé. Lacuna e silêncio são exatamente os defeitos que não
 * produzem erro visível: as outras telas continuam mostrando números, só que de
 * uma janela incompleta.
 */
function IntegridadeDaColeta() {
  const saude = usePeriodico(buscarSaude);
  const s = saude.dado;
  if (!s) return null;

  // Agrupado por fonte, não linha a linha. Uma fonte de cadência lenta gera uma
  // lacuna por ciclo: sem agrupar, a lista virava vinte linhas do mesmo GDACS e
  // escondia a única fonte que estivesse de fato calada.
  const porFonte = new Map<string, { n: number; maior: number; ate: string }>();
  for (const l of s.lacunas) {
    const atual = porFonte.get(l.source_id);
    if (!atual || l.duracao_seg > atual.maior) {
      porFonte.set(l.source_id, { n: (atual?.n ?? 0) + 1, maior: l.duracao_seg, ate: l.ate });
    } else {
      atual.n += 1;
    }
  }

  const problemas: Array<{ rotulo: string; detalhe: string }> = [
    ...[...porFonte.entries()].map(([fonte, g]) => ({
      rotulo: `${g.n} ${g.n === 1 ? "lacuna" : "lacunas"} em ${fonte}`,
      detalhe: `maior de ${Math.round(g.maior / 60)} min, a mais recente até ${instante(g.ate)}`,
    })),
    ...s.silenciosas.map((id) => ({
      rotulo: `${id} silenciosa`,
      detalhe: "fonte ativa que parou de responder",
    })),
  ];
  if (s.linhas_na_particao_default > 0) {
    problemas.push({
      rotulo: "partição DEFAULT ocupada",
      detalhe: `${inteiro(s.linhas_na_particao_default)} linhas fora da partição de destino`,
    });
  }

  return (
    <section className={`cartao integridade${s.saudavel ? "" : " com-falha"}`}>
      <header className="integridade-cabecalho">
        <span className={`estado estado-${s.saudavel ? "ok" : "bloqueado"}`}>
          <i aria-hidden="true">{s.saudavel ? "●" : "■"}</i>
          {s.saudavel ? "Coleta íntegra" : "Coleta com falha"}
        </span>
        <span className="integridade-fila">
          {inteiro(s.payloads_aguardando_analise)} payloads na fila de análise
        </span>
      </header>
      {problemas.length ? (
        <ul className="integridade-lista">
          {problemas.map((p) => (
            <li key={p.rotulo}>
              <strong>{p.rotulo}</strong>
              <span>{p.detalhe}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="nota" style={{ marginTop: 8 }}>
          Sem lacuna de coleta, sem fonte silenciosa e sem linha na partição DEFAULT. A fila de
          análise é a distância entre o que foi coletado e o que já virou evento.
        </p>
      )}
    </section>
  );
}

export function TelaFontes() {
  const fontes = usePeriodico(buscarFontes);
  const lista = fontes.dado ?? [];
  const coletando = lista.filter((f) => f.ativa).length;
  const validadas = lista.filter((f) => f.validado_em).length;

  return (
    <div className="pagina">
      <CabecalhoTela
        selo="COBERTURA E INTEGRIDADE"
        contexto={
          <>
            {coletando} de {lista.length} coletando · atualizado {relogio(fontes.atualizadoEm)}
          </>
        }
        titulo="Fontes de dados"
        descricao="Estado técnico, cadência e limites de redistribuição de cada integração."
      />

      <div className="painel-grid">
        <Painel
          titulo="COLETANDO"
          valor={inteiro(coletando)}
          destaque={lista.length ? `${Math.round((coletando / lista.length) * 100)}%` : undefined}
          papel="ok"
          nota={`de ${lista.length} catalogadas`}
        />
        <Painel titulo="ENDPOINT VALIDADO" valor={inteiro(validadas)} nota="sondado, não suposto" />
        <Painel
          titulo="BLOQUEADAS POR LICENÇA"
          valor={inteiro(lista.filter((f) => f.redistribuicao === "interna").length)}
          destaque="G4"
          papel="atencao"
          nota="participam da correlação"
        />
        <Painel
          titulo="EXIGEM CHAVE"
          valor={inteiro(lista.filter((f) => f.requer_chave).length)}
          nota="cadastro necessário"
        />
      </div>

      <IntegridadeDaColeta />

      <p className="aviso-demo">
        <strong>Licença é coluna no banco, não anotação.</strong> Fonte marcada como uso interno
        participa da correlação e da contagem de confiança, e a API remove o conteúdo dela da
        resposta. Copernicus e INMET só saem desse estado com resposta jurídica por escrito.
      </p>

      <div className="tabela-rolagem">
        <table className="tabela tabela-fontes">
          <thead>
            <tr>
              <th>Fonte</th>
              <th>Estado</th>
              <th>Licença</th>
              <th>Cadência</th>
              <th>Última coleta</th>
              <th className="num">Erros 1 h</th>
            </tr>
          </thead>
          <tbody>
            {lista.map((f) => {
              const e = estadoDaFonte(f);
              return (
                <tr key={f.source_id}>
                  <td data-label="Fonte">
                    <strong>{f.nome}</strong>
                    {f.endpoint && <span className="endpoint">{f.endpoint}</span>}
                  </td>
                  <td data-label="Estado">
                    {/* Símbolo + rótulo + cor. Nunca cor sozinha. */}
                    <span className={`estado estado-${e.papel}`}>
                      <i aria-hidden="true">{e.simbolo}</i>
                      {e.rotulo}
                    </span>
                  </td>
                  <td data-label="Licença" className={f.redistribuicao === "interna" ? "restrito" : ""}>
                    {ROTULO_LICENCA[f.redistribuicao] ?? f.redistribuicao}
                  </td>
                  <td data-label="Cadência">
                    {/* Fonte não sondada não tem cadência medida. Desenhar a barra
                        daria aparência de fato a um valor que é só um padrão herdado. */}
                    {f.validado_em ? <Cadencia segundos={f.intervalo_poll_seg} /> : <span className="nao-medido">não medida</span>}
                  </td>
                  <td data-label="Última coleta">{instante(f.ultima_coleta_ok)}</td>
                  <td className="num" data-label="Erros 1 h">{f.erros_1h}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="nota">
        Cadência medida a partir do <code>cache-control</code> de cada fonte, não estimada. Sondar
        mais rápido que o cache declarado devolve o mesmo dado com timestamp novo.
      </p>
    </div>
  );
}

function EstadoCarregando({ texto }: { texto: string }) {
  return (
    <div className="estado-carregando" role="status">
      <i aria-hidden="true" />
      <span>{texto}</span>
    </div>
  );
}

// ── reservadas ─────────────────────────────────────────────────────────────

function Reservada({ titulo, texto, icone }: { titulo: string; texto: string; icone: NomeIcone }) {
  return (
    <div className="vazio">
      <span className="vazio-icone" aria-hidden="true">
        <Icone nome={icone} tamanho="lg" />
      </span>
      <h2>{titulo}</h2>
      <p>{texto}</p>
      <Link to="/mapa" className="acao-principal">
        <Icone nome="globe" tamanho="sm" />
        Ir para o mapa global
      </Link>
    </div>
  );
}

export function TelaAlertas() {
  return (
    <Reservada
      icone="bell"
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
      icone="file"
      titulo="Relatórios"
      texto="Reservada de propósito. Um relatório sobre dado não deduplicado contaria o mesmo
        evento como vários — exatamente o problema que o produto existe para resolver. Entra depois
        da Fase 2."
    />
  );
}
