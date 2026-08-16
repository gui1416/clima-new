/** Tipos da API de produto.
 *
 * Espelham `api/clima/api/esquemas.py`. Os dados de demonstração do protótipo
 * saíram: o back-end agora entrega sismos reais do USGS.
 *
 * `magnitude` e `metricaRotulo` acompanham `severidade` em todo lugar, de
 * propósito — a faixa nunca aparece sem a grandeza que a originou.
 */

export type Severidade = "critical" | "high" | "moderate";

export const SEVERIDADES: readonly Severidade[] = ["critical", "high", "moderate"] as const;

export const ROTULO_SEVERIDADE: Record<Severidade, string> = {
  critical: "Crítico",
  high: "Alto",
  moderate: "Moderado",
};

export interface EventoResumo {
  id: string;
  titulo: string;
  tipo: string;
  lugar: string | null;
  lat: number;
  lon: number;
  ocorrido_em: string;
  atualizado_em: string;
  severidade: Severidade;
  magnitude: number | null;
  metrica_rotulo: string;
  profundidade_km: number | null;
  /** Fontes independentes que confirmam. Vale 1 até o motor de correlação existir. */
  fontes_confirmando: number;
  revisoes: number;
  status: string;
}

export interface Procedencia {
  fonte: string;
  nome: string;
  source_event_id: string;
  observado_em: string;
  revisado_em: string;
  revisoes: number;
  status: string;
  magnitude: number | null;
  profundidade_km: number | null;
  lugar: string | null;
  atribuicao: string | null;
  /** Fonte com licença restrita: conta, mas não entrega conteúdo (portão G4). */
  conteudo_restrito: boolean;
}

export interface EventoDetalhe extends EventoResumo {
  metricas: Record<string, unknown>;
  xrefs: Record<string, unknown>;
  procedencia: Procedencia[];
}

export interface Pagina {
  total: number;
  itens: EventoResumo[];
  deduplicado: boolean;
  aviso: string | null;
}

export interface Estatisticas {
  eventos_total: number;
  por_severidade: Partial<Record<Severidade, number>>;
  por_status: Record<string, number>;
  magnitude_maxima: number | null;
  ultimo_evento_em: string | null;
  janela_horas: number;
  fontes_ativas: number;
  deduplicado: boolean;
}

export interface SaudeFonte {
  source_id: string;
  nome: string;
  ativa: boolean;
  redistribuicao: "livre" | "atribuicao" | "interna";
  intervalo_poll_seg: number;
  ultima_coleta_ok: string | null;
  ultimo_erro_em: string | null;
  erros_1h: number;
}
