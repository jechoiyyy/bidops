import { FormEvent, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { Panel } from "../components/common/Panel";
import { api } from "../lib/api";
import { formatDeadline, present } from "../lib/format";
import "../styles/operations-workflow-relaxed.css";
import type { AgencyPortal, AttachmentQueueItem } from "../lib/types";
import { gradeVariant } from "../lib/grade";

interface PortalDraft {
  id: number | null;
  agency_pattern: string;
  system_name: string;
  search_url_template: string;
  enabled: boolean;
  note: string;
}

const emptyDraft: PortalDraft = {
  id: null,
  agency_pattern: "",
  system_name: "",
  search_url_template: "",
  enabled: true,
  note: "",
};


function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function groupByAgency(items: AttachmentQueueItem[]): [string, AttachmentQueueItem[]][] {
  const groups = new Map<string, AttachmentQueueItem[]>();
  for (const item of items) {
    const agency = item.agency?.trim() || "발주기관 미확인";
    groups.set(agency, [...(groups.get(agency) ?? []), item]);
  }
  return [...groups.entries()];
}

function isDeadlineAlert(value: string | null): boolean {
  return Boolean(value && (value.startsWith("D-") || value.startsWith("마감 지남")));
}

function PortalForm({
  draft,
  saving,
  onChange,
  onSubmit,
  onCancel,
}: {
  draft: PortalDraft;
  saving: boolean;
  onChange: (draft: PortalDraft) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
}) {
  return (
    <form className="portal-form" onSubmit={onSubmit}>
      <div className="attachment-section-label">{draft.id === null ? "기관 등록" : "기관 정보 수정"}</div>
      <label>
        기관 매칭 문자열
        <input value={draft.agency_pattern} onChange={(event) => onChange({ ...draft, agency_pattern: event.target.value })} placeholder="예: 한국수자원공사" required />
      </label>
      <label>
        조달시스템 이름
        <input value={draft.system_name} onChange={(event) => onChange({ ...draft, system_name: event.target.value })} placeholder="예: 기관 전자조달시스템" required />
      </label>
      <label>
        검색 주소 템플릿
        <input value={draft.search_url_template} onChange={(event) => onChange({ ...draft, search_url_template: event.target.value })} placeholder="https://...?...={bid_no}&title={title}" required />
      </label>
      <p className="portal-form-help">{`{bid_no}`}와 {`{title}`}은 공고 값으로 바뀌며 URL 인코딩됩니다.</p>
      <label>
        비고
        <textarea value={draft.note} onChange={(event) => onChange({ ...draft, note: event.target.value })} rows={2} placeholder="담당자가 참고할 내용을 입력합니다." />
      </label>
      <label className="portal-enabled-control">
        <input type="checkbox" checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} />
        검색 주소 자동 생성에 사용
      </label>
      <div className="portal-form-actions">
        <button className="attachment-primary-button" type="submit" disabled={saving}>{saving ? "저장 중" : draft.id === null ? "기관 등록" : "수정 저장"}</button>
        {draft.id !== null ? <button className="attachment-secondary-button" type="button" onClick={onCancel}>취소</button> : null}
      </div>
    </form>
  );
}

function PortalRow({ portal, onEdit }: { portal: AgencyPortal; onEdit: (portal: AgencyPortal) => void }) {
  return (
    <div className="portal-row">
      <div className="portal-row-main">
        <strong>{present(portal.system_name, "조달시스템 이름 미확인")}</strong>
        <span>{present(portal.agency_pattern, "기관 매칭 문자열 미확인")}</span>
        <code>{present(portal.search_url_template, "검색 주소 템플릿 미확인")}</code>
      </div>
      <Badge label={portal.enabled ? "사용 중" : "사용 안 함"} variant={portal.enabled ? "evidence-confirmed" : "neutral"} />
      <button className="attachment-secondary-button" type="button" onClick={() => onEdit(portal)}>수정</button>
    </div>
  );
}

function QueueNotice({ item, runId }: { item: AttachmentQueueItem; runId: string }) {
  const deadline = formatDeadline(item.deadline_at);
  return (
    <article className="attachment-queue-item">
      <div className="attachment-queue-item-head">
        <div className="attachment-queue-item-title">
          <Link to={`/judgments/${item.id}?run=${encodeURIComponent(runId)}`}>{present(item.title, "공고명 미확인")}</Link>
          <span className="mono tabular-nums">{present(item.bid_no, "공고번호 미확인")}</span>
        </div>
        <div className="attachment-queue-badges">
          <Badge label={item.grade} variant={gradeVariant(item.grade)} />
          <Badge label={item.readiness} variant="readiness" />
        </div>
      </div>
      <div className="attachment-queue-meta">
        <span>{present(item.agency, "발주기관 미확인")}</span>
        <span aria-hidden="true">·</span>
        <span className={isDeadlineAlert(deadline) ? "attachment-deadline is-alert" : "attachment-deadline"}>{deadline}</span>
      </div>
      <div className="attachment-queue-portal">
        {item.matched_portal && item.search_url ? (
          <>
            <span>{present(item.matched_portal.system_name, "조달시스템 이름 미확인")}</span>
            <a href={item.search_url} target="_blank" rel="noreferrer">검색 주소 열기
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
            </a>
          </>
        ) : (
          <>
            <span className="attachment-no-portal">등록된 조달시스템 없음</span>
            <span>{item.portal_message}</span>
          </>
        )}
      </div>
    </article>
  );
}

export function AttachmentsPage() {
  const [searchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const queryClient = useQueryClient();
  const queueQuery = useQuery({
    queryKey: ["attachment-queue", runId],
    queryFn: () => api.getAttachmentQueue(runId as string),
    enabled: Boolean(runId),
    staleTime: 15_000,
  });
  const portalsQuery = useQuery({ queryKey: ["portals"], queryFn: api.getPortals, staleTime: 15_000 });
  const [draft, setDraft] = useState<PortalDraft>(() => ({
    ...emptyDraft,
    agency_pattern: searchParams.get("agency") ?? "",
  }));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const grouped = useMemo(() => groupByAgency(queueQuery.data?.items ?? []), [queueQuery.data?.items]);
  const editPortal = (portal: AgencyPortal) => {
    setFormError(null);
    setDraft({ ...portal, note: portal.note ?? "" });
  };

  const savePortal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    const payload = {
      agency_pattern: draft.agency_pattern,
      system_name: draft.system_name,
      search_url_template: draft.search_url_template,
      enabled: draft.enabled,
      note: draft.note.trim() || null,
    };
    try {
      if (draft.id === null) await api.createPortal(payload);
      else await api.updatePortal(draft.id, payload);
      setDraft(emptyDraft);
      await queryClient.invalidateQueries({ queryKey: ["portals"] });
      await queryClient.invalidateQueries({ queryKey: ["attachment-queue", runId] });
    } catch (error) {
      setFormError(errorMessage(error, "기관 조달시스템 저장에 실패했습니다."));
    } finally {
      setSaving(false);
    }
  };

  if (!runId) return <EmptyState title="선택된 회차가 없습니다." description="상단의 실행 회차 선택기에서 회차를 선택하십시오." />;
  if (queueQuery.isLoading) return <div className="attachments-loading" role="status" aria-live="polite">첨부 미확보 공고를 불러오는 중입니다.</div>;
  if (queueQuery.error) return <EmptyState title="첨부 확보 큐를 불러오지 못했습니다." description={errorMessage(queueQuery.error, "첨부 확보 큐를 확인할 수 없습니다.")} action={{ label: "다시 시도", onClick: () => void queueQuery.refetch() }} />;

  return (
    <div className="attachments-page">
      <header className="attachments-page-header">
        <div>
          <div className="attachments-eyebrow">운영 · 첨부 확보</div>
          <h2>첨부 미확보 공고</h2>
          <p>발주기관 시스템에서 문서를 확인하고 원문 보관소에 등록합니다.</p>
        </div>
        <div className="attachments-count"><strong className="mono tabular-nums">{queueQuery.data?.total ?? 0}</strong><span>건 미확보</span></div>
      </header>

      <div className="attachments-layout">
        <section className="attachments-queue" aria-label="첨부 미확보 공고 큐">
          {grouped.length === 0 ? <EmptyState title="첨부 미확보 공고가 없습니다." description="선택한 회차의 모든 공고에 첨부가 등록되어 있습니다." /> : null}
          {grouped.map(([agency, items]) => (
            <section className="attachment-agency-group" key={agency}>
              <div className="attachment-agency-heading"><h3>{agency}</h3><span className="mono tabular-nums">{items.length}건</span></div>
              <div className="attachment-queue-list">{items.map((item) => <QueueNotice key={item.id} item={item} runId={runId} />)}</div>
            </section>
          ))}
        </section>

        <aside className="attachments-side-column">
          <Panel title="기관 조달시스템" action={<span className="panel-meta">{portalsQuery.data?.length ?? 0}개 등록</span>}>
            {portalsQuery.isLoading ? <div className="inline-loading" role="status" aria-live="polite">기관 목록을 불러오는 중입니다.</div> : null}
            {portalsQuery.error ? <p className="attachment-upload-error">{errorMessage(portalsQuery.error, "기관 목록을 확인할 수 없습니다.")}</p> : null}
            <div className="portal-list">{(portalsQuery.data ?? []).map((portal) => <PortalRow key={portal.id} portal={portal} onEdit={editPortal} />)}</div>
            {!portalsQuery.isLoading && !portalsQuery.error && (portalsQuery.data ?? []).length === 0 ? <p className="attachment-empty">등록된 조달시스템이 없습니다.</p> : null}
            <PortalForm draft={draft} saving={saving} onChange={setDraft} onSubmit={(event) => void savePortal(event)} onCancel={() => setDraft(emptyDraft)} />
            {formError ? <p className="attachment-upload-error" role="alert">{formError}</p> : null}
          </Panel>
          <Panel title="확보 기준">
            <ul className="attachment-policy-list">
              <li>허용 형식 HWP · HWPX · PDF</li>
              <li>파일당 최대 50MB</li>
              <li>등록 파일은 서버가 생성한 보관 경로에 저장</li>
              <li>나라장터 제공 첨부는 삭제할 수 없음</li>
            </ul>
          </Panel>
        </aside>
      </div>
    </div>
  );
}
