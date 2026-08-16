/** Tipos da camada de dados.
 *
 * Os nomes de campo vêm do protótipo, porque os dados de demonstração são
 * extraídos dele mecanicamente. **Este não é o contrato final**: a API de produto
 * (Fase 3) define o formato real, e aí este arquivo é reescrito a partir do
 * schema dela, não o contrário.
 */

export type Severidade = "critical" | "high" | "moderate";

export const SEVERIDADES: readonly Severidade[] = ["critical", "high", "moderate"] as const;

export const ROTULO_SEVERIDADE: Record<Severidade, string> = {
  critical: "Crítico",
  high: "Alto",
  moderate: "Moderado",
};

export interface Evento {
  id: string;
  title: string;
  place: string;
  country: string;
  /** ISO 3166-1 numérico como string ('076' Brasil). Liga evento a país. */
  countryId: string;
  region: string;
  type: string;
  severity: Severidade;
  severityLabel: string;
  time: string;
  lat: number;
  lon: number;
  people: string;
  exposure: number;
  /** Quantas fontes independentes confirmam. É a métrica do diferencial. */
  sources: number;
  confidence: number;
  /** Métrica física — nunca deve aparecer sem ela ao lado da severidade. */
  metric: string;
  metricLabel: string;
  summary: string;
  sourceNames: string[];
  updates: string[];
  times: string[];
}

export interface ArquivoEventosDemo {
  demo: true;
  origem: string;
  geradoEm: string;
  eventos: Evento[];
}

export interface PropriedadesPais {
  iso: string;
  nome: string;
}
