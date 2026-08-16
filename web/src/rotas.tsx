/** As seis rotas do protótipo.
 *
 * Só as duas que o dado atual sustenta estão implementadas: o mapa e a lista de
 * eventos. As outras quatro dependem da API de produto (Fase 3) ou do motor de
 * correlação (Fase 2), e ficam como espaço reservado explícito.
 *
 * Espaço reservado que diz o que falta é honesto; tela preenchida com número
 * inventado seria exatamente o problema que o produto existe para combater.
 */

import { useEffect, useState } from "react";

import { carregarEventosDemo } from "./dados/carregar";
import { MapaGlobal } from "./mapa/MapaGlobal";
import { ROTULO_SEVERIDADE, type Evento } from "./tipos";

export interface Rota {
  caminho: string;
  rotulo: string;
  icone: string;
  grupo: "monitoramento" | "distribuicao";
  /** Ocupa a área toda, sem padding nem rolagem própria. */
  telaCheia?: boolean;
}

export const ROTAS: readonly Rota[] = [
  { caminho: "/mapa", rotulo: "Mapa global", icone: "◎", grupo: "monitoramento", telaCheia: true },
  { caminho: "/eventos", rotulo: "Eventos", icone: "≡", grupo: "monitoramento" },
  { caminho: "/procedencia", rotulo: "Procedência", icone: "⑃", grupo: "monitoramento" },
  { caminho: "/fontes", rotulo: "Fontes de dados", icone: "◈", grupo: "monitoramento" },
  { caminho: "/alertas", rotulo: "Alertas & webhooks", icone: "△", grupo: "distribuicao" },
  { caminho: "/relatorios", rotulo: "Relatórios", icone: "▭", grupo: "distribuicao" },
] as const;

const AVISO_DEMO = (
  <p className="aviso-demo">
    <strong>Dados de demonstração.</strong> Os 18 eventos vêm do protótipo, não de fonte real. A
    ingestão do USGS já grava <code>payload_raw</code> (Fase 0), mas o parser e o motor de
    correlação ainda não existem — Fases 1 e 2.
  </p>
);

export function TelaMapa() {
  return <MapaGlobal />;
}

export function TelaEventos() {
  const [eventos, setEventos] = useState<Evento[]>([]);

  useEffect(() => {
    let vivo = true;
    carregarEventosDemo().then((e) => vivo && setEventos(e));
    return () => {
      vivo = false;
    };
  }, []);

  return (
    <div className="pagina">
      {AVISO_DEMO}
      <table className="tabela">
        <thead>
          <tr>
            <th>Evento</th>
            <th>Local</th>
            <th>Tipo</th>
            <th>Severidade</th>
            {/* Métrica ao lado da severidade, sempre. */}
            <th>Métrica</th>
            <th className="num">Fontes</th>
            <th className="num">Confiança</th>
          </tr>
        </thead>
        <tbody>
          {eventos.map((e) => (
            <tr key={e.id}>
              <td>{e.title}</td>
              <td>
                {e.place}, {e.country}
              </td>
              <td>{e.type}</td>
              <td>
                <i className={`ponto ${e.severity}`} /> {ROTULO_SEVERIDADE[e.severity]}
              </td>
              <td>
                <strong>{e.metric}</strong> {e.metricLabel}
              </td>
              <td className="num">{e.sources}</td>
              <td className="num">{e.confidence}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Reservada({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div className="vazio">
      <h2>{titulo}</h2>
      <p>{texto}</p>
    </div>
  );
}

export function TelaProcedencia() {
  return (
    <Reservada
      titulo="Painel de procedência"
      texto="A tela do diferencial: mostra, campo por campo, o que cada fonte afirma sobre o mesmo
        evento e onde elas discordam. Depende do motor de correlação e de event_field_claims —
        Fase 2. Não existe no protótipo; precisa ser desenhada."
    />
  );
}

export function TelaFontes() {
  return (
    <Reservada
      titulo="Fontes de dados"
      texto="Saúde dos conectores, última coleta e lacunas. O back-end já expõe isso em
        /saude/fontes; falta a API de produto para consumir aqui — Fase 3."
    />
  );
}

export function TelaAlertas() {
  return (
    <Reservada
      titulo="Alertas & webhooks"
      texto="Fora do escopo da v1 por decisão de plano, e depende do portão G3: se o usuário
        gratuito primário for desenvolvedor, esta tela perde prioridade para o portal de API."
    />
  );
}

export function TelaRelatorios() {
  return (
    <Reservada
      titulo="Relatórios"
      texto="Fora do escopo da v1. Um relatório gerado sobre dado não deduplicado repetiria o
        mesmo evento como se fossem vários — o que é o problema, não o produto."
    />
  );
}
