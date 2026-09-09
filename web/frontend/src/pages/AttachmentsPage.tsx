import { FormEvent, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Paperclip, Search } from "lucide-react";
import { RunPickerField, useSelectedRun } from "../components/runs/RunPicker";
import {
  Caption,
  DataTable,
  DetailFooter,
  DetailHeader,
  Facts,
  ListRecord,
  Note,
  Section,
  StatusToken,
} from "../components/runs/RunStatusPrimitives";
import { api } from "../lib/api";
import { formatDeadline, formatNumber, present } from "../lib/format";
import type { AgencyPortal, AttachmentQueueItem } from "../lib/types";

// 첨부 확보 탭. 좌: 회차 선택과 첨부 미확보 공고 목록. 우: 고른 공고의 발주기관·
// 실제 미확보 사유·기관 포털 진입점. 기관 포털 등록·수정 전체 양식은 없애지
// 않고 `기관 포털 관리` 대화상자로 옮겼다.

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

function isDeadlineAlert(value: string): boolean {
  return value.startsWith("D-") || value.startsWith("마감 지남");
}

/**
 * 서버는 첨부가 없다는 사실과 그 사유(`portal_message`)만 준다. 어떤 문서가
 * 빠졌는지(제안요청서·과업지시서)는 계약에 없으므로 화면이 만들어 붙이지
 * 않는다. 확인할 수 있는 것만 말한다.
 */
function missingReason(item: AttachmentQueueItem): string {
  if (item.attachment_status === "none" && item.attachment_count === 0) return "등록된 첨부가 없습니다";
  if (item.attachment_count === 0) return "확보된 첨부가 없습니다";
  return `첨부 ${formatNumber(item.attachment_count)}건이 있으나 확보 대기 상태입니다`;
}

function PortalManagerDialog({
  open,
  onClose,
  runId,
}: {
  open: boolean;
  onClose: () => void;
  runId: string | null;
}) {
  const queryClient = useQueryClient();
  const portalsQuery = useQuery({ queryKey: ["portals"], queryFn: api.getPortals, staleTime: 15_000, enabled: open });
  const [draft, setDraft] = useState<PortalDraft>(emptyDraft);
  const [actorName, setActorName] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const portals = portalsQuery.data ?? [];

  const editPortal = (portal: AgencyPortal) => {
    setFormError(null);
    setDraft({ ...portal, note: portal.note ?? "" });
  };

  const savePortal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    if (!actorName.trim()) {
      setFormError("담당자 이름을 입력해야 저장할 수 있습니다.");
      return;
    }
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
      if (draft.id === null) await api.createPortal(payload, actorName.trim());
      else await api.updatePortal(draft.id, payload, actorName.trim());
      setDraft(emptyDraft);
      await queryClient.invalidateQueries({ queryKey: ["portals"] });
      await queryClient.invalidateQueries({ queryKey: ["attachment-queue", runId] });
    } catch (error) {
      // 충돌이면 창을 닫지 않고 입력을 남겨 다시 시도할 수 있게 한다.
      setFormError(errorMessage(error, "기관 조달시스템 저장에 실패했습니다."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog isOpen={open} onOpenChange={(next) => { if (!next && !saving) onClose(); }} purpose="form" width={720} maxHeight="90dvh">
      <div className="rs-dialog-body" data-astryx-theme="bidops">
        <DialogHeader title="기관 포털 관리" onOpenChange={(next) => { if (!next && !saving) onClose(); }} />
        <div className="rs-dialog-scroll">
          <Section title="등록된 기관 조달시스템" action={<Caption as="span">{portalsQuery.isError ? "미확인" : `${portals.length}개`}</Caption>}>
            {portalsQuery.isLoading ? <Caption>기관 목록을 불러오는 중입니다.</Caption> : null}
            {portalsQuery.error ? (
              <div className="rs-inline-error" role="alert">
                <Text as="span">기관 목록을 확인할 수 없습니다. 등록 0건이라는 뜻이 아닙니다.</Text>
                <Button label="다시 시도" size="sm" onClick={() => void portalsQuery.refetch()} />
              </div>
            ) : null}
            {!portalsQuery.isLoading && !portalsQuery.error && portals.length === 0 ? (
              <Caption>등록된 조달시스템이 0건입니다.</Caption>
            ) : null}
            <div className="rs-portal-list">
              {portals.map((portal) => (
                <div className="rs-portal-row" key={portal.id}>
                  <div>
                    <Text as="span" weight="semibold">{present(portal.system_name, "조달시스템 이름 미확인")}</Text>
                    <Caption as="span">{present(portal.agency_pattern, "기관 매칭 문자열 미확인")}</Caption>
                    <Caption as="span"><span className="rs-mono">{present(portal.search_url_template, "검색 주소 템플릿 미확인")}</span></Caption>
                  </div>
                  <div className="rs-row">
                    <StatusToken label={portal.enabled ? "사용 중" : "사용 안 함"} />
                    <Button label="수정" size="sm" onClick={() => editPortal(portal)} />
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <form className="rs-section" onSubmit={(event) => void savePortal(event)}>
            <div className="rs-section-head">
              <Text as="p" weight="semibold">{draft.id === null ? "기관 등록" : `기관 정보 수정 · ${draft.system_name || draft.id}`}</Text>
              {draft.id !== null ? <Button label="새 등록으로" size="sm" onClick={() => setDraft(emptyDraft)} /> : null}
            </div>
            <div className="rs-form-grid">
              <label className="rs-field">
                <span>기관 매칭 문자열 <em>필수</em></span>
                <input
                  value={draft.agency_pattern}
                  onChange={(event) => setDraft({ ...draft, agency_pattern: event.target.value })}
                  placeholder="예: 한국수자원공사"
                  disabled={saving}
                  required
                />
              </label>
              <label className="rs-field">
                <span>조달시스템 이름 <em>필수</em></span>
                <input
                  value={draft.system_name}
                  onChange={(event) => setDraft({ ...draft, system_name: event.target.value })}
                  placeholder="예: 기관 전자조달시스템"
                  disabled={saving}
                  required
                />
              </label>
            </div>
            <label className="rs-field">
              <span>검색 주소 템플릿 <em>필수</em></span>
              <input
                value={draft.search_url_template}
                onChange={(event) => setDraft({ ...draft, search_url_template: event.target.value })}
                placeholder="https://...?...={bid_no}&title={title}"
                disabled={saving}
                required
              />
              <small>{"{bid_no}"}와 {"{title}"}은 공고 값으로 바뀌며 URL 인코딩됩니다.</small>
            </label>
            <label className="rs-field">
              <span>비고</span>
              <textarea
                value={draft.note}
                onChange={(event) => setDraft({ ...draft, note: event.target.value })}
                rows={2}
                placeholder="담당자가 참고할 내용을 입력합니다."
                disabled={saving}
              />
            </label>
            <label className="rs-field">
              <span>담당자 이름 <em>필수</em></span>
              <input
                value={actorName}
                onChange={(event) => setActorName(event.target.value)}
                placeholder="예: 홍길동"
                autoComplete="name"
                disabled={saving}
                required
              />
              <small>감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아닙니다.</small>
            </label>
            <label className="rs-check-field">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
                disabled={saving}
              />
              <span>검색 주소 자동 생성에 사용</span>
            </label>
            {formError ? <Text className="rs-dialog-error" as="p" role="alert">{formError}</Text> : null}
            <div className="rs-dialog-actions">
              <Button label="취소" isDisabled={saving} onClick={onClose} />
              <Button
                label={saving ? "저장 중…" : draft.id === null ? "기관 등록" : "수정 저장"}
                variant="primary"
                type="submit"
                isDisabled={saving || !actorName.trim() || !draft.agency_pattern.trim() || !draft.system_name.trim() || !draft.search_url_template.trim()}
              />
            </div>
          </form>
        </div>
      </div>
    </Dialog>
  );
}

export function AttachmentsPage({ panelId = "run-status-panel-attachments" }: { panelId?: string }) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { runs, selectedRunId, selectRun, isPending, isError, refetch } = useSelectedRun();
  const [selectedNoticeId, setSelectedNoticeId] = useState<number | null>(null);
  const [listQuery, setListQuery] = useState("");
  const [portalDialogOpen, setPortalDialogOpen] = useState(false);

  const queueQuery = useQuery({
    queryKey: ["attachment-queue", selectedRunId],
    queryFn: () => api.getAttachmentQueue(selectedRunId as string),
    enabled: Boolean(selectedRunId),
    staleTime: 15_000,
  });
  const portalsQuery = useQuery({ queryKey: ["portals"], queryFn: api.getPortals, staleTime: 15_000 });

  const items = useMemo(() => queueQuery.data?.items ?? [], [queueQuery.data]);
  const term = listQuery.trim();
  const visible = items.filter((item) => term === ""
    || `${item.title ?? ""} ${item.agency ?? ""} ${item.bid_no ?? ""}`.includes(term));
  const selected = items.find((item) => item.id === selectedNoticeId) ?? visible[0] ?? items[0] ?? null;

  const portalCount = portalsQuery.data?.length ?? null;

  return (
    <div className="rs-workspace" id={panelId} role="tabpanel" aria-label="첨부 확보">
      <section className="rs-list-pane" aria-label="첨부 미확보 목록">
        <header className="rs-list-head">
          <Text className="rs-list-title" as="p">첨부 미확보 목록</Text>
          <Caption as="span">{queueQuery.isError ? "미확인" : `${(queueQuery.data?.total ?? items.length).toLocaleString("ko-KR")}건`}</Caption>
        </header>
        <div className="rs-list-filters">
          <RunPickerField
            label="첨부 확보 대상 회차"
            runs={runs}
            selectedRunId={selectedRunId}
            onSelect={(runId) => { selectRun(runId); setSelectedNoticeId(null); }}
            isPending={isPending}
            isError={isError}
            onRetry={refetch}
          />
          <TextInput
            label="공고·발주기관 검색"
            isLabelHidden
            placeholder="공고명·발주기관 검색"
            value={listQuery}
            onChange={setListQuery}
            startIcon={Search}
            hasClear
            size="sm"
          />
        </div>
        <div className="rs-list-scroll">
          {!selectedRunId && !isPending ? (
            <div className="rs-list-empty">
              <Paperclip aria-hidden="true" />
              <Text as="p">선택된 회차가 없습니다.</Text>
              <Caption>회차를 고르면 그 회차의 첨부 미확보 공고를 확인할 수 있습니다.</Caption>
            </div>
          ) : null}
          {queueQuery.isPending && selectedRunId ? <div className="rs-list-empty"><Caption>첨부 미확보 공고를 불러오는 중입니다.</Caption></div> : null}
          {queueQuery.error ? (
            <div className="rs-list-empty" role="alert">
              <Paperclip aria-hidden="true" />
              <Text as="p">첨부 확보 큐를 불러오지 못했습니다.</Text>
              <Caption>조회 실패는 미확보 0건이 아닙니다.</Caption>
              <Button label="다시 시도" size="sm" onClick={() => void queueQuery.refetch()} />
            </div>
          ) : null}
          {!queueQuery.isPending && !queueQuery.error && items.length === 0 && selectedRunId ? (
            <div className="rs-list-empty">
              <Paperclip aria-hidden="true" />
              <Text as="p">첨부 미확보 공고가 0건입니다.</Text>
              <Caption>선택한 회차의 모든 공고에 첨부가 등록되어 있습니다.</Caption>
            </div>
          ) : null}
          {!queueQuery.isPending && items.length > 0 && visible.length === 0 ? (
            <div className="rs-list-empty">
              <Search aria-hidden="true" />
              <Text as="p">조건에 맞는 공고가 없습니다.</Text>
              <Button label="검색 초기화" size="sm" onClick={() => setListQuery("")} />
            </div>
          ) : null}
          {visible.map((item) => (
            <ListRecord
              key={item.id}
              selected={selected?.id === item.id}
              onSelect={() => setSelectedNoticeId(item.id)}
              item={{
                id: String(item.id),
                title: present(item.title, "공고명 미확인"),
                subtitle: present(item.agency, "발주기관 미확인"),
                meta: `${present(item.grade, "등급 미확인")} · ${present(item.readiness, "준비 상태 미확인")} · ${formatDeadline(item.deadline_at)}`,
                status: "미확보",
              }}
            />
          ))}
        </div>
        <footer className="rs-list-foot">
          <Caption>
            {selectedRunId ? `회차 ${selectedRunId}` : "회차 미선택"} · 미확보 {queueQuery.isError ? "미확인" : `${(queueQuery.data?.total ?? 0).toLocaleString("ko-KR")}건`}
            {" · "}
            {portalsQuery.error
              ? "등록된 포털은 조회 실패로 미확인"
              : portalCount === null ? "등록된 포털 조회 중" : `등록된 포털 ${portalCount}개`}
          </Caption>
        </footer>
      </section>

      <section className="rs-detail-pane" aria-label="확인할 공고">
        {selected ? (
          <>
            <DetailHeader
              eyebrow="첨부 확보 · 확인할 공고"
              title={present(selected.title, "공고명 미확인")}
              status="미확보"
              statusDescription="첨부 원문을 아직 확보하지 못한 상태입니다."
            >
              <div className="rs-row rs-spread">
                <Text as="span" weight="semibold">{present(selected.agency, "발주기관 미확인")}</Text>
                <Caption as="span">
                  <span className={isDeadlineAlert(formatDeadline(selected.deadline_at)) ? "rs-mono" : "rs-mono"}>
                    {formatDeadline(selected.deadline_at)}
                  </span>
                </Caption>
              </div>
            </DetailHeader>

            <div className="rs-detail-scroll">
              <Section title="확보 상태">
                <Facts
                  items={[
                    ["첨부 상태", missingReason(selected)],
                    ["등록된 첨부", `${formatNumber(selected.attachment_count)}건`],
                    ["첨부 출처", selected.attachment_status === "g2b" ? "나라장터 제공" : selected.attachment_status === "manual" ? "담당자 등록" : "없음"],
                    ["공고번호", <span className="rs-mono" key="bid">{present(selected.bid_no, "공고번호 미확인")}</span>],
                  ]}
                />
                <Caption>
                  미확보 문서의 종류는 확인되지 않았습니다. 기관 조달시스템에서 필요한 원문을 확인해 주세요.
                </Caption>
              </Section>

              <Note title="기관 조달시스템에서 원문을 확인합니다">
                첨부가 없다는 사실만으로 공고의 적합성 등급이나 참여 준비 상태를 낮추지 않습니다.
              </Note>

              <Section title="기관 검색 경로">
                <Facts
                  items={[
                    ["발주기관", present(selected.agency, "발주기관 미확인")],
                    ["공고 식별자", <span className="rs-mono" key="key">{selected.notice_key}</span>],
                    [
                      "등록된 포털",
                      selected.matched_portal
                        ? present(selected.matched_portal.system_name, "조달시스템 이름 미확인")
                        : portalsQuery.error
                          ? "포털 조회 실패 · 미확인"
                          : "등록된 조달시스템 없음",
                    ],
                    ["포털 안내", present(selected.portal_message, "안내 없음")],
                  ]}
                />
                {selected.matched_portal && selected.search_url ? (
                  <div className="rs-link-row">
                    <a href={selected.search_url} target="_blank" rel="noreferrer">기관 검색 주소 열기</a>
                  </div>
                ) : (
                  <Caption>
                    {portalsQuery.error
                      ? "포털 목록을 확인하지 못해 검색 주소를 만들 수 없습니다. 등록 0건이라는 뜻이 아닙니다."
                      : "이 기관에 등록된 검색 주소가 없습니다. 기관 포털 관리에서 등록할 수 있습니다."}
                  </Caption>
                )}
              </Section>

              <Section title="관련 검토 상태">
                <Facts
                  items={[
                    ["적합성 등급", present(selected.grade, "등급 미확인")],
                    ["참여 준비 상태", present(selected.readiness, "준비 상태 미확인")],
                    ["표본 역할", present(selected.sample_role, "기록 없음")],
                    ["수집 층", present(selected.collection_bucket, "기록 없음")],
                  ]}
                />
                <Caption>
                  적합성 등급·참여 준비 상태·추적 선택·최종 Go/No-Go는 각각 별도 판단입니다. 첨부 확보가
                  그중 어느 것도 대신하지 않습니다.
                </Caption>
              </Section>

              <Section title="확보 기준">
                <DataTable
                  caption="첨부 확보 기준"
                  headings={["항목", "기준"]}
                  rows={[
                    { id: "format", cells: ["허용 형식", "HWP · HWPX · PDF"] },
                    { id: "size", cells: ["파일당 최대", "50MB"] },
                    { id: "path", cells: ["보관 경로", "서버가 생성한 보관 경로에만 저장"] },
                    { id: "g2b", cells: ["나라장터 제공 첨부", "삭제할 수 없음"] },
                  ]}
                />
              </Section>
            </div>

            <DetailFooter note="원문 확보와 추적 결정은 별도">
              <Button
                label="공고 판정 열기"
                size="sm"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  if (selectedRunId) next.set("run", selectedRunId);
                  navigate({ pathname: `/judgments/${selected.id}`, search: next.toString() });
                }}
              />
              <Button label="기관 포털 관리" size="sm" variant="primary" onClick={() => setPortalDialogOpen(true)} />
            </DetailFooter>
          </>
        ) : (
          <div className="rs-detail-empty">
            <Paperclip aria-hidden="true" />
            <Text as="p">확인할 공고를 고르십시오.</Text>
            <Caption>회차를 고르면 그 회차에서 첨부를 확보하지 못한 공고를 확인할 수 있습니다.</Caption>
            <Button label="기관 포털 관리" size="sm" onClick={() => setPortalDialogOpen(true)} />
          </div>
        )}
      </section>

      <PortalManagerDialog open={portalDialogOpen} onClose={() => setPortalDialogOpen(false)} runId={selectedRunId} />
    </div>
  );
}
