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
import {
  ROTULO_SEVERIDADE,
  SEVERIDADES,
  type SaudeFonte,
  type Severidade,
} from "./tipos";

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

      {/* Do mesmo `est` que alimenta os painéis: o aviso e os números precisam
          responder à mesma pergunta com o mesmo filtro. */}
      {e && <AvisoDedup aviso={e.aviso} />}

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

      <div className="tres-colunas">
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
            É a única parte do produto que não é commodity. USGS e EMSC só se sobrepõem acima de
            M 4,5, então a maioria dos eventos tem fonte única — e a interface diz isso em vez de
            sugerir consolidação que não houve.
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

      <div className="duas-colunas">
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
      <div className="medidor" role="img" aria-label={`${unica} eventos com uma fonte, ${multifonte} com duas ou mais`}>
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

export function TelaFontes() {
  const fontes = usePeriodico(buscarFontes);
  const lista = fontes.dado ?? [];
  const coletando = lista.filter((f) => f.ativa).length;
  const validadas = lista.filter((f) => f.validado_em).length;

  return (
    <div className="pagina">
      <div className="cabecalho-pagina">
        <span className="atualizado">atualizado {relogio(fontes.atualizadoEm)}</span>
      </div>

      <div className="painel-grid">
        <Painel titulo="COLETANDO" valor={inteiro(coletando)} nota={`de ${lista.length} catalogadas`} />
        <Painel titulo="ENDPOINT VALIDADO" valor={inteiro(validadas)} nota="sondado, não suposto" />
        <Painel
          titulo="BLOQUEADAS POR LICENÇA"
          valor={inteiro(lista.filter((f) => f.redistribuicao === "interna").length)}
          nota="participam da correlação"
        />
        <Painel
          titulo="EXIGEM CHAVE"
          valor={inteiro(lista.filter((f) => f.requer_chave).length)}
          nota="cadastro necessário"
        />
      </div>

      <p className="aviso-demo">
        <strong>Licença é coluna no banco, não anotação.</strong> Fonte marcada como uso interno
        participa da correlação e da contagem de confiança, e a API remove o conteúdo dela da
        resposta. Copernicus e INMET só saem desse estado com resposta jurídica por escrito.
      </p>

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
                <td>
                  <strong>{f.nome}</strong>
                  {f.endpoint && <span className="endpoint">{f.endpoint}</span>}
                </td>
                <td>
                  {/* Símbolo + rótulo + cor. Nunca cor sozinha. */}
                  <span className={`estado estado-${e.papel}`}>
                    <i aria-hidden="true">{e.simbolo}</i>
                    {e.rotulo}
                  </span>
                </td>
                <td className={f.redistribuicao === "interna" ? "restrito" : ""}>
                  {ROTULO_LICENCA[f.redistribuicao] ?? f.redistribuicao}
                </td>
                <td>
                  {/* Fonte não sondada não tem cadência medida. Desenhar a barra
                      daria aparência de fato a um valor que é só um padrão herdado. */}
                  {f.validado_em ? <Cadencia segundos={f.intervalo_poll_seg} /> : <span className="nao-medido">não medida</span>}
                </td>
                <td>{instante(f.ultima_coleta_ok)}</td>
                <td className="num">{f.erros_1h}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="nota">
        Cadência medida a partir do <code>cache-control</code> de cada fonte, não estimada. Sondar
        mais rápido que o cache declarado devolve o mesmo dado com timestamp novo.
      </p>
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
