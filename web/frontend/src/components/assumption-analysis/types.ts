export type Kind = 'document_fact' | 'company_fact' | 'assumption' | 'unknown' | 'interpretation';
export type EvidenceLink = {source_id: string; quote: string; status: string};
export type Paragraph = {kind: Kind; body: string; refs: EvidenceLink[]; warnings: string[]};
export type Section = {key: string; title: string; paragraphs: Paragraph[]};
export type Report = {sections: Section[]; complete: boolean; warnings: string[]};
export type EconomicRow = {id: string; months: number; price_ratio: string; support_cost_won: string; revenue_ex_vat_won: string; cost_won: string; assumed_balance_won: string; sensitivity_only: boolean};
export type Source = {id: string; kind: Kind; text: string; locations: Record<string, unknown>[]};
export type Analysis = {
  id: string; notice_id: number; status: string; error_code: string | null; call_count: number; latency_ms: number;
  input_sha256: string; input_version_id: string;
  scenario: {settings: {model: string; reasoning_effort: string}; assumptions: Source[]; economics: {rows: EconomicRow[]}};
  stages: {stage: string; part: number; status: string; latency_ms: number; error_code: string | null; result: Report | null}[];
  active_call: {stage: string; part: number; started_at: string} | null;
  sources: Source[]; report: Report | null;
};
export type Preview = {preview_id: string; input_sha256: string; input: Record<string, unknown>; changed_fields: string[]; previous_preview_id: string | null};
export const kindLabels: Record<Kind, string> = {document_fact: '문서 사실 주장', company_fact: '회사 사실 주장', assumption: '가정', unknown: '미확인', interpretation: '모델 해석'};
