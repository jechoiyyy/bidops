import { useEffect, useId, useRef, useState, type KeyboardEvent, type MutableRefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Badge, type BadgeVariant } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { describeCompanyApiError } from "../../lib/apiErrors";
import {
  COMPANY_GRAPH_DEFAULT_DEPTH,
  COMPANY_GRAPH_DEFAULT_LIMIT,
  COMPANY_NODE_TYPE_ORDER,
  companyApi,
  companyKeys,
  companyNodeStatusLabel,
  companyNodeTypeLabel,
  companyOriginLabel,
  companyRelationTypeLabel,
  type CompanyFactStatus,
  type CompanyKnowledgeGraphQuery,
  type CompanyKnowledgeGraphView,
  type CompanyNodeOrigin,
  type CompanyProfileView,
  type JsonValue,
  type PublicKnowledgeEdge,
  type PublicKnowledgeNode,
  type Uuid,
} from "../../lib/companyApi";
import "../../styles/company-workspace.css";

/*
 * 회사 지식 그래프의 관계 목록과 근거 패널(공통 계약 §3·§4, DEMO-04 spec).
 *
 * - 서버가 준 노드·관계만 그린다. 관계·경로·순위·누락 값을 브라우저가 만들지 않는다.
 *   노드는 유형별로 묶을 뿐이며(묶음 순서는 순위가 아니다) 묶음 안은 서버 순서다.
 * - 노드를 중심으로 다시 보면 `root_node_id`로 서버에 다시 묻는다(BFS는 서버 몫).
 *   중심·깊이·최대 노드 수는 주소(`graph_root`·`graph_depth`·`graph_limit`)가 정본이다.
 * - 잘림(`truncated`·`omitted_node_count`)은 문장으로 알린다. 잘림은 분석 누락의 증거가 아니다.
 * - 노드·관계 행을 누르면(클릭·Enter·Space) 근거 패널이 열리고 `evidence_ids`마다
 *   `GET .../profile-evidence/{id}`를 읽는다. 닫으면(버튼·Escape) 연 행으로 초점이 돌아간다.
 * - 확실성(시나리오 확정/확정/추정/미확인)과 출처 구분(가상 설정/공개 문서 사실/모델 해석)을
 *   색이 아니라 문자로 적는다. unknown·null은 0이나 "없음"으로 바꾸지 않는다.
 * - 응답의 회사·그래프 버전·hash·온톨로지가 프로필과 다르면 목록을 그리지 않는다.
 */

const DEPTH_OPTIONS = [1, 2, 3] as const;
const LIMIT_OPTIONS = [10, 50, 100, 200, 500] as const;
const STABLE_KEY = /^[a-z][a-z0-9_.:-]{0,127}$/;

/** 그래프 탐색 상태를 담는 주소 검색 인자. */
export const GRAPH_SEARCH_PARAMS = { root: "graph_root", depth: "graph_depth", limit: "graph_limit" } as const;

interface GraphParams {
  root: string | null;
  depth: number;
  limit: number;
}

function boundedInt(raw: string | null, fallback: number, min: number, max: number): number {
  if (raw === null || !/^[0-9]+$/.test(raw)) return fallback;
  const value = Number(raw);
  return value >= min && value <= max ? value : fallback;
}

/** 허용 범위 밖의 주소 값은 기본값으로 되돌린다(서버에 잘못된 query를 보내지 않는다). */
function readGraphParams(params: URLSearchParams): GraphParams {
  const root = params.get(GRAPH_SEARCH_PARAMS.root);
  return {
    root: root !== null && STABLE_KEY.test(root) ? root : null,
    depth: boundedInt(params.get(GRAPH_SEARCH_PARAMS.depth), COMPANY_GRAPH_DEFAULT_DEPTH, 1, 3),
    limit: boundedInt(params.get(GRAPH_SEARCH_PARAMS.limit), COMPANY_GRAPH_DEFAULT_LIMIT, 1, 500),
  };
}

type Selection = { kind: "node" | "edge"; id: string; graphKey: string };

function triggerKey(kind: "node" | "edge", id: string): string {
  return `${kind}:${id}`;
}

function statusVariant(status: CompanyFactStatus): BadgeVariant {
  if (status === "unknown") return "evidence-unknown";
  if (status === "inferred") return "evidence-inferred";
  return "evidence-confirmed";
}

function shortSha(value: string): string {
  return value.slice(0, 12);
}

// ---------------------------------------------------------------------------
// 값 표시(계약 §3의 타입별). 값을 고치거나 채우지 않고 자리만 옮긴다.

function isRecord(value: JsonValue): value is { [key: string]: JsonValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function jsonText(value: JsonValue | undefined): string {
  if (value === undefined || value === null) return "미확인";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(jsonText).join(", ");
  return Object.entries(value).map(([key, entry]) => `${key}: ${jsonText(entry)}`).join(" · ");
}

function countText(value: JsonValue | undefined, unit: string): string {
  return typeof value === "number" ? `${value.toLocaleString("ko-KR")}${unit}` : "미확인";
}

function textOrUnknown(value: JsonValue | undefined): string {
  return typeof value === "string" && value.trim() ? value : "미확인";
}

function nodeValueText(node: PublicKnowledgeNode): string {
  if (node.status === "unknown") return "값 미확인";
  const value = node.value;
  if (value === null) return "값 없음";
  switch (node.type) {
    case "company":
    case "domain":
    case "technology":
    case "qualification":
      return typeof value === "string" ? value : jsonText(value);
    case "capability":
      if (isRecord(value)) {
        const scope = value.scope === "core" ? "주력 역량" : value.scope === "non_core" ? "비주력 역량" : `범위 ${jsonText(value.scope)}`;
        return `${scope} · ${textOrUnknown(value.description)}`;
      }
      break;
    case "staff_group":
      if (isRecord(value)) {
        return `역할 ${textOrUnknown(value.role)} · 전체 ${countText(value.total, "명")} · 투입 가능 ${countText(value.available, "명")} · 기준일 ${textOrUnknown(value.as_of)}`;
      }
      break;
    case "project":
      if (isRecord(value)) {
        return `역할 ${textOrUnknown(value.role)} · 범위 ${textOrUnknown(value.scope)} · 금액 ${countText(value.amount_krw, "원")} · 기간 ${textOrUnknown(value.started_on)} ~ ${textOrUnknown(value.ended_on)}`;
      }
      break;
    case "evidence":
      if (isRecord(value)) return `근거 사실 ${textOrUnknown(value.fact_key)}`;
      break;
    case "notice":
      if (isRecord(value)) return `공고 번호 ${jsonText(value.notice_id)}`;
      break;
    case "requirement":
      if (isRecord(value)) {
        const mandatory = value.mandatory === true ? "필수" : value.mandatory === false ? "선택" : "필수 여부 미확인";
        return `${textOrUnknown(value.text)} · ${mandatory}`;
      }
      break;
  }
  return jsonText(value);
}

function evidenceCountText(count: number): string {
  return count === 0 ? "연결 근거 없음" : `연결 근거 ${count}개`;
}

// ---------------------------------------------------------------------------

export function KnowledgeGraph({ companyId, profile }: { companyId: Uuid; profile: CompanyProfileView }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = readGraphParams(searchParams);
  const query: CompanyKnowledgeGraphQuery = {
    graph_version_id: profile.graph_version_id,
    root_node_id: params.root,
    depth: params.depth,
    limit: params.limit,
  };
  const queryKey = companyKeys.knowledgeGraph(companyId, query);
  const graphKey = JSON.stringify(queryKey);
  const graphQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => companyApi.getKnowledgeGraph(companyId, query, { signal }),
    retry: false,
  });

  const [rawSelection, setSelection] = useState<Selection | null>(null);
  // 중심·깊이·최대 수가 바뀌면 이전 목록의 선택은 쓰지 않는다.
  const selection = rawSelection && rawSelection.graphKey === graphKey ? rawSelection : null;
  const sectionRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const centerRef = useRef<HTMLParagraphElement | null>(null);
  const focusCenterOnLoad = useRef(false);
  const headingId = useId();

  const updateParams = (patch: Partial<GraphParams>, replace: boolean) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      const merged = { ...readGraphParams(previous), ...patch };
      if (merged.root === null) next.delete(GRAPH_SEARCH_PARAMS.root);
      else next.set(GRAPH_SEARCH_PARAMS.root, merged.root);
      if (merged.depth === COMPANY_GRAPH_DEFAULT_DEPTH) next.delete(GRAPH_SEARCH_PARAMS.depth);
      else next.set(GRAPH_SEARCH_PARAMS.depth, String(merged.depth));
      if (merged.limit === COMPANY_GRAPH_DEFAULT_LIMIT) next.delete(GRAPH_SEARCH_PARAMS.limit);
      else next.set(GRAPH_SEARCH_PARAMS.limit, String(merged.limit));
      return next;
    }, { replace });
  };

  const recenter = (root: string | null) => {
    focusCenterOnLoad.current = true;
    setSelection(null);
    updateParams({ root }, false);
  };

  const focusTrigger = (key: string) => {
    const triggers = sectionRef.current?.querySelectorAll<HTMLElement>("[data-graph-trigger]") ?? [];
    for (const element of Array.from(triggers)) {
      if (element.dataset.graphTrigger === key) { element.focus(); return; }
    }
  };

  const closePanel = () => {
    if (!selection) return;
    const key = triggerKey(selection.kind, selection.id);
    setSelection(null);
    focusTrigger(key);
  };

  const openPanel = (kind: "node" | "edge", id: string) => {
    setSelection({ kind, id, graphKey });
  };

  const selectionKey = selection ? `${selection.graphKey}|${triggerKey(selection.kind, selection.id)}` : null;
  useEffect(() => {
    if (selectionKey !== null) panelRef.current?.focus();
  }, [selectionKey]);

  useEffect(() => {
    if (focusCenterOnLoad.current && graphQuery.isSuccess) {
      focusCenterOnLoad.current = false;
      centerRef.current?.focus();
    }
  }, [graphQuery.isSuccess, graphKey]);

  const onSectionKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || !selection) return;
    if (event.target instanceof HTMLSelectElement) return;
    event.preventDefault();
    closePanel();
  };

  const data = graphQuery.data;
  const identityProblem = data ? identityMismatch(data, companyId, profile) : null;
  const state = graphQuery.isPending ? "loading" : graphQuery.isError || identityProblem ? "error" : data && data.edges.length === 0 ? "empty" : "ready";
  const limitOptions = [...new Set<number>([...LIMIT_OPTIONS, params.limit])].sort((left, right) => left - right);

  return (
    <section
      ref={sectionRef}
      className="cw-section kg"
      aria-labelledby={headingId}
      aria-busy={state === "loading"}
      data-graph-state={state}
      data-testid="company-graph"
      onKeyDown={onSectionKeyDown}
    >
      <header className="kg-header">
        <h3 id={headingId}>관계 탐색</h3>
        <p className="cw-caption">
          서버가 돌려준 노드와 관계만 보여 줍니다. 화면이 관계·경로·순위를 만들거나 빠진 값을 채우지 않습니다.
          노드나 관계를 누르면 연결된 근거를 엽니다.
        </p>
        <p className="cw-caption" data-testid="graph-version">
          그래프 버전 {profile.graph_version_id} · 그래프 sha256 {shortSha(profile.graph_sha256)} · 온톨로지 {profile.ontology_version}
        </p>
      </header>

      <div className="kg-controls" role="group" aria-label="관계 탐색 조건">
        <p ref={centerRef} tabIndex={-1} className="kg-center" data-testid="graph-center">
          {centerText(data && !identityProblem ? data : null, params.root, state)}
        </p>
        <label className="kg-control">
          <span>탐색 깊이</span>
          <select
            aria-label="탐색 깊이"
            value={params.depth}
            onChange={(event) => updateParams({ depth: Number(event.target.value) }, true)}
          >
            {DEPTH_OPTIONS.map((depth) => <option key={depth} value={depth}>{depth}단계</option>)}
          </select>
        </label>
        <label className="kg-control">
          <span>최대 노드 수</span>
          <select
            aria-label="최대 노드 수"
            value={params.limit}
            onChange={(event) => updateParams({ limit: Number(event.target.value) }, true)}
          >
            {limitOptions.map((limit) => <option key={limit} value={limit}>{limit}개</option>)}
          </select>
        </label>
        {params.root !== null ? (
          <Button label="회사 중심으로 돌아가기" size="sm" variant="secondary" onClick={() => recenter(null)} />
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="kg-loading" role="status" data-testid="graph-loading">
          관계 목록을 불러오는 중입니다. 아직 완료된 목록이 아닙니다.
        </p>
      ) : graphQuery.isError ? (
        <EmptyState
          tone="error"
          compact
          title="관계 목록을 불러오지 못했습니다."
          problem={describeCompanyApiError(graphQuery.error, "관계 목록을 불러오지 못했습니다.")}
          action={{ label: "관계 목록 다시 불러오기", onClick: () => { void graphQuery.refetch(); } }}
        />
      ) : identityProblem ? (
        <EmptyState
          tone="error"
          compact
          title="관계 목록의 버전이 프로필과 맞지 않습니다."
          description={`${identityProblem} 다른 버전의 관계를 섞어 보여 주지 않습니다. 프로필을 다시 불러오십시오.`}
        />
      ) : data ? (
        <GraphBody
          data={data}
          params={params}
          selection={selection}
          onOpen={openPanel}
          onRecenter={recenter}
          onClose={closePanel}
          panelRef={panelRef}
          companyId={companyId}
          profileVersionId={profile.profile_version_id}
        />
      ) : null}
    </section>
  );
}

function identityMismatch(data: CompanyKnowledgeGraphView, companyId: Uuid, profile: CompanyProfileView): string | null {
  if (data.company_id !== companyId) return "응답의 회사가 이 화면의 회사와 다릅니다.";
  if (data.graph_version_id !== profile.graph_version_id) return `프로필 그래프 버전 ${profile.graph_version_id}와 응답 버전 ${data.graph_version_id}가 다릅니다.`;
  if (data.graph_sha256 !== profile.graph_sha256) return "프로필과 응답의 그래프 sha256이 다릅니다.";
  if (data.ontology_version !== profile.ontology_version) return `프로필 온톨로지 ${profile.ontology_version}와 응답 온톨로지 ${data.ontology_version}가 다릅니다.`;
  return null;
}

function centerText(data: CompanyKnowledgeGraphView | null, root: string | null, state: string): string {
  if (state === "loading") return root === null ? "중심: 회사(기본) · 불러오는 중" : `중심: ${root} · 불러오는 중`;
  if (!data) return root === null ? "중심: 회사(기본)" : `중심: ${root}`;
  const node = root === null ? data.nodes.find((entry) => entry.type === "company") : data.nodes.find((entry) => entry.id === root);
  if (!node) return root === null ? "중심: 회사(기본)" : `중심: ${root}`;
  return `중심: ${node.label} (${companyNodeTypeLabel(node.type)})${root === null ? " · 회사 기본 중심" : ""}`;
}

interface GraphBodyProps {
  data: CompanyKnowledgeGraphView;
  params: GraphParams;
  selection: Selection | null;
  onOpen: (kind: "node" | "edge", id: string) => void;
  onRecenter: (root: string | null) => void;
  onClose: () => void;
  panelRef: MutableRefObject<HTMLElement | null>;
  companyId: Uuid;
  profileVersionId: Uuid;
}

function GraphBody({ data, params, selection, onOpen, onRecenter, onClose, panelRef, companyId, profileVersionId }: GraphBodyProps) {
  const nodesById = new Map(data.nodes.map((node) => [node.id, node]));
  const rootId = params.root ?? data.nodes.find((node) => node.type === "company")?.id ?? null;
  const groups = COMPANY_NODE_TYPE_ORDER
    .map((type) => ({ type, nodes: data.nodes.filter((node) => node.type === type) }))
    .filter((group) => group.nodes.length > 0);
  // 계약 밖 유형이 오면 숨기지 않고 마지막 묶음으로 둔다.
  const knownTypes = new Set<string>(COMPANY_NODE_TYPE_ORDER);
  const otherNodes = data.nodes.filter((node) => !knownTypes.has(node.type));
  const endLabel = (id: string) => nodesById.get(id)?.label ?? `목록에 없는 노드 ${id}`;
  const selectedNode = selection?.kind === "node" ? nodesById.get(selection.id) ?? null : null;
  const selectedEdge = selection?.kind === "edge" ? data.edges.find((edge) => edge.id === selection.id) ?? null : null;
  const truncated = data.truncated || data.omitted_node_count > 0;

  const renderNode = (node: PublicKnowledgeNode) => {
    const isRoot = node.id === rootId;
    const pressed = selection?.kind === "node" && selection.id === node.id;
    return (
      <li
        key={node.id}
        className={`kg-item${pressed ? " is-selected" : ""}`}
        data-node-id={node.id}
        data-node-type={node.type}
        data-node-status={node.status}
        data-node-origin={node.origin}
        aria-current={isRoot ? "true" : undefined}
      >
        <button
          type="button"
          className="kg-row"
          data-graph-trigger={triggerKey("node", node.id)}
          aria-pressed={pressed}
          onClick={() => onOpen("node", node.id)}
        >
          <span className="kg-row-title">{node.label}</span>
          <span className="kg-row-meta">
            <Badge variant={statusVariant(node.status)} label={companyNodeStatusLabel(node.status, node.origin)} data-status-label />
            <span data-origin-label>{companyOriginLabel(node.origin)}</span>
            <span>{evidenceCountText(node.evidence_ids.length)}</span>
          </span>
          <span className="kg-row-value" data-node-value>{nodeValueText(node)}</span>
        </button>
        {isRoot ? (
          <span className="kg-root-mark cw-caption">현재 중심</span>
        ) : (
          <button
            type="button"
            className="kg-recenter"
            aria-label={`${node.label} 중심으로 보기`}
            onClick={() => onRecenter(node.type === "company" ? null : node.id)}
          >
            중심으로 보기
          </button>
        )}
      </li>
    );
  };

  return (
    <>
      <p className="cw-caption" data-testid="graph-summary">
        표시 노드 {data.nodes.length}개 · 관계 {data.edges.length}개 · 깊이 {params.depth}단계 · 최대 {params.limit}개
        {truncated ? "" : " · 이 깊이 안의 노드를 모두 표시했습니다"}
      </p>
      {truncated ? (
        <p className="kg-truncation" role="note" aria-label="목록 잘림 안내" data-testid="graph-truncation">
          <strong>목록이 잘렸습니다.</strong>{" "}
          이 중심에서 깊이 {params.depth}단계 안의 노드 중 <span data-testid="graph-omitted-count">{data.omitted_node_count}</span>개를
          표시하지 않았습니다(최대 {params.limit}개). 잘림은 분석이 빠졌거나 관계가 없다는 증거가 아닙니다.
          최대 노드 수를 늘리거나 깊이를 줄여 다시 보십시오.
        </p>
      ) : null}
      <div className={`kg-layout${selection ? " has-panel" : ""}`}>
        <div className="kg-lists">
          <div className="kg-nodes" role="region" aria-label="노드 목록">
            <h4>노드 · 유형별</h4>
            {groups.map((group) => (
              <section key={group.type} className="kg-group" data-node-group={group.type} aria-label={`${companyNodeTypeLabel(group.type)} 노드`}>
                <h5>{companyNodeTypeLabel(group.type)} <span className="cw-caption">{group.nodes.length}개</span></h5>
                <ul className="kg-list">{group.nodes.map(renderNode)}</ul>
              </section>
            ))}
            {otherNodes.length > 0 ? (
              <section className="kg-group" data-node-group="other" aria-label="기타 유형 노드">
                <h5>기타 유형 <span className="cw-caption">{otherNodes.length}개</span></h5>
                <ul className="kg-list">{otherNodes.map(renderNode)}</ul>
              </section>
            ) : null}
          </div>
          <div className="kg-relations" role="region" aria-label="관계 목록">
            <h4>관계 <span className="cw-caption">{data.edges.length}개</span></h4>
            {data.edges.length === 0 ? (
              <p className="cw-caption" data-testid="graph-empty">
                이 중심에서 깊이 {params.depth}단계 안에 서버가 돌려준 관계가 없습니다. 관계가 없다는 판정이 아니며, 깊이를 늘리거나 다른 노드를 중심으로 보십시오.
              </p>
            ) : (
              <ul className="kg-list">
                {data.edges.map((edge) => {
                  const pressed = selection?.kind === "edge" && selection.id === edge.id;
                  return (
                    <li
                      key={edge.id}
                      className={`kg-item kg-relation${pressed ? " is-selected" : ""}`}
                      data-edge-id={edge.id}
                      data-edge-type={edge.type}
                      data-edge-status={edge.status}
                    >
                      <button
                        type="button"
                        className="kg-row"
                        data-graph-trigger={triggerKey("edge", edge.id)}
                        aria-pressed={pressed}
                        onClick={() => onOpen("edge", edge.id)}
                      >
                        <span className="kg-relation-line">
                          <span className="kg-end" data-edge-from>{endLabel(edge.from_id)}</span>
                          <span className="kg-relation-type" data-edge-label>— {companyRelationTypeLabel(edge.type)} →</span>
                          <span className="kg-end" data-edge-to>{endLabel(edge.to_id)}</span>
                        </span>
                        <span className="kg-row-meta">
                          <Badge variant={statusVariant(edge.status)} label={companyNodeStatusLabel(edge.status, edge.origin)} data-status-label />
                          <span data-origin-label>{companyOriginLabel(edge.origin)}</span>
                          <span>{evidenceCountText(edge.evidence_ids.length)}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
        {selection && (selectedNode || selectedEdge) ? (
          <EvidencePanel
            panelRef={panelRef}
            companyId={companyId}
            profileVersionId={profileVersionId}
            title={selectedNode ? selectedNode.label : selectedEdge ? `${endLabel(selectedEdge.from_id)} — ${companyRelationTypeLabel(selectedEdge.type)} → ${endLabel(selectedEdge.to_id)}` : ""}
            kindLabel={selectedNode ? `${companyNodeTypeLabel(selectedNode.type)} 노드` : "관계"}
            status={(selectedNode ?? selectedEdge)!.status}
            origin={(selectedNode ?? selectedEdge)!.origin}
            value={selectedNode ? nodeValueText(selectedNode) : null}
            evidenceIds={(selectedNode ?? selectedEdge)!.evidence_ids}
            onClose={onClose}
          />
        ) : null}
      </div>
    </>
  );
}

interface EvidencePanelProps {
  panelRef: MutableRefObject<HTMLElement | null>;
  companyId: Uuid;
  profileVersionId: Uuid;
  title: string;
  kindLabel: string;
  status: CompanyFactStatus;
  origin: CompanyNodeOrigin;
  value: string | null;
  evidenceIds: Uuid[];
  onClose: () => void;
}

function EvidencePanel({ panelRef, companyId, profileVersionId, title, kindLabel, status, origin, value, evidenceIds, onClose }: EvidencePanelProps) {
  const titleId = useId();
  return (
    <aside
      ref={panelRef}
      tabIndex={-1}
      className="kg-panel"
      aria-labelledby={titleId}
      data-testid="graph-evidence-panel"
    >
      <header className="kg-panel-header">
        <p className="cw-caption">근거 · {kindLabel}</p>
        <h4 id={titleId}>{title}</h4>
        <Button label="근거 닫기" size="sm" variant="ghost" onClick={onClose} />
      </header>
      <dl className="cw-facts">
        <dt>확실성</dt><dd data-status-label>{companyNodeStatusLabel(status, origin)}</dd>
        <dt>출처 구분</dt><dd data-origin-label>{companyOriginLabel(origin)}</dd>
        {value !== null ? <><dt>값</dt><dd>{value}</dd></> : null}
      </dl>
      {origin === "fictional_scenario" && status === "confirmed" ? (
        <p className="cw-caption">가상회사 시나리오에서 정한 값입니다. 실제 회사 사실이 아닙니다.</p>
      ) : null}
      {evidenceIds.length === 0 ? (
        <p className="kg-no-evidence" data-testid="graph-no-evidence">
          {status === "unknown"
            ? "미확인 항목이라 연결된 근거가 없습니다. 근거가 없다는 것이 미보유나 부적합을 뜻하지 않습니다."
            : "서버가 연결한 근거가 없습니다."}
        </p>
      ) : (
        <ol className="kg-evidence-list">
          {evidenceIds.map((evidenceId, index) => (
            <ProfileEvidenceItem
              key={evidenceId}
              companyId={companyId}
              evidenceId={evidenceId}
              ordinal={index + 1}
              profileVersionId={profileVersionId}
            />
          ))}
        </ol>
      )}
    </aside>
  );
}

function ProfileEvidenceItem({ companyId, evidenceId, ordinal, profileVersionId }: { companyId: Uuid; evidenceId: Uuid; ordinal: number; profileVersionId: Uuid }) {
  const evidenceQuery = useQuery({
    queryKey: companyKeys.profileEvidence(companyId, evidenceId),
    queryFn: ({ signal }) => companyApi.getProfileEvidence(companyId, evidenceId, { signal }),
    retry: false,
  });
  if (evidenceQuery.isPending) {
    return <li className="kg-evidence" data-evidence-id={evidenceId}><p role="status">근거 {ordinal}을 불러오는 중입니다.</p></li>;
  }
  if (evidenceQuery.isError) {
    const problem = describeCompanyApiError(evidenceQuery.error, "근거를 불러오지 못했습니다.");
    return (
      <li className="kg-evidence" data-evidence-id={evidenceId}>
        <p role="alert">근거 {ordinal}을 불러오지 못했습니다. {problem.title} {problem.detail}{problem.code ? ` · 오류 코드 ${problem.code}` : ""}</p>
        <Button label={`근거 ${ordinal} 다시 조회`} size="sm" onClick={() => { void evidenceQuery.refetch(); }} />
      </li>
    );
  }
  const evidence = evidenceQuery.data;
  const versionMismatch = evidence.profile_version_id !== profileVersionId;
  const idMismatch = evidence.evidence_id !== evidenceId;
  return (
    <li className="kg-evidence" data-evidence-id={evidenceId} data-evidence-loaded="true">
      <p className="cw-caption">근거 {ordinal} · {companyOriginLabel(evidence.origin)} 원본 인용</p>
      <blockquote className="kg-quote">{evidence.quote}</blockquote>
      <dl className="cw-facts">
        <dt>사실 키</dt><dd data-evidence-fact-key>{evidence.fact_key}</dd>
        <dt>출처 구분</dt><dd>{companyOriginLabel(evidence.origin)}</dd>
        <dt>원본 sha256</dt><dd className="cw-caption" data-evidence-sha title="원본 sha256 앞 12자리">{shortSha(evidence.source_sha256)}</dd>
      </dl>
      {versionMismatch || idMismatch ? (
        <p role="alert" className="kg-evidence-warning">
          {idMismatch ? "요청한 근거와 다른 근거가 돌아왔습니다. " : ""}
          {versionMismatch ? "이 근거는 현재 프로필 버전의 근거가 아닙니다. " : ""}
          현재 프로필의 근거로 쓰지 마십시오.
        </p>
      ) : null}
    </li>
  );
}
