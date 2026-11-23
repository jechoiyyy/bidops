import { Button } from "@astryxdesign/core/Button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { decideIngest, ingestDetail, ingestLimit, ingestListKey, type IngestDetail, type IngestStatus, type IngestSummary } from "../../lib/companyWikiIngestApi";
import { formatDateTime } from "../../lib/format";
import { qualityStatusLabel, qualityStatusVariant } from "../../lib/qualityStatus";
import { requestActorInput, useRememberedActorName } from "../common/ActorField";
import { TechnicalInfo } from "../common/TechnicalInfo";
import { Badge } from "../common/Badge";
import { CriteriaDialog, CancelButton, DialogActions } from "../criteria/CriteriaPrimitives";
import { IngestProblem } from "./IngestProblem";
import { wikiUrl } from "./WikiBody";
import { WikiSplit } from "./WikiSplit";
import { wikiValue } from "./WikiState";

const labels: Record<IngestStatus, string> = {
  queued: "접수됨", extracting: "요구사항 추출 중", classifying: "분류 중", awaiting_review: "검토 대기",
  approved: "승인됨", applying: "반영 중", applied: "반영 완료", failed: "실패", rejected: "반려", aborted: "중단",
};

function fileSize(bytes: number) {
  const mb = bytes >= 1024 * 1024;
  const value = bytes / (mb ? 1024 * 1024 : 1024);
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + (mb ? " MB" : " KB");
}

const mediaNames: Record<string, string> = {
  "application/x-hwp": "한글(HWP) 문서", "application/hwp+zip": "한글(HWPX) 문서", "application/pdf": "PDF 문서",
};

function Review({ run }: { run: IngestDetail }) {
  return <>
    <h3>분류 요약</h3>
    {run.units.length ? <ul>{run.units.map(unit => <li key={unit.id}>{unit.title} · {unit.count}건</li>)}</ul> : <p>배정된 업무 단위가 없어요.</p>}
    <p>미분류 건수 · {wikiValue(run.unassigned_count)}<br/>문서에 있으나 목록에 없는 번호 수 · {wikiValue(run.unlisted_id_count)}</p>
    <table><caption>요구사항별 배정</caption><thead><tr><th>번호</th><th>명칭</th><th>업무 단위</th></tr></thead>
      <tbody>{run.assignments.map(item => <tr key={item.req_id}><th scope="row">{item.req_id}</th>
        <td>{item.name}</td><td>{item.unit_titles.join(", ") || "미분류"}</td></tr>)}</tbody></table>
  </>;
}

function RunDetail({ id }: { id: string }) {
  const query = useQuery(ingestDetail(id));
  const run = query.data;
  const actor = useRememberedActorName().trim();
  const [action, setAction] = useState<"approve" | "reject" | null>(null);
  const [needsName, setNeedsName] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const decision = useMutation({
    mutationFn: (note: string | null) => decideIngest(id, actor, note),
    onSuccess: result => {
      setAction(null);
      client.setQueryData(ingestDetail(id).queryKey, result);
      void client.invalidateQueries({ queryKey: ingestListKey });
    },
    onError: error => {
      if (error instanceof ApiError && error.status === 409) {
        setAction(null);
        void query.refetch();
        void client.invalidateQueries({ queryKey: ingestListKey });
      }
    },
  });
  useEffect(() => {
    if (run?.status === "applied") void client.invalidateQueries({ queryKey: ["company-wiki"] });
  }, [client, run?.status]);
  function checkName() {
    if (actor) return true;
    setAction(null);
    setNeedsName(true);
    requestActorInput();
    return false;
  }
  if (query.error) return <><IngestProblem error={query.error}/>
    <Button label="상세 다시 조회" onClick={() => { void query.refetch(); }}/></>;
  if (!run) return <p role="status">넣기 기록을 불러오고 있어요.</p>;
  const awaiting = run.status === "awaiting_review";
  const dialogOpen = awaiting && action !== null;
  return <>
    <h2>{run.project_title}</h2>
    <p role="status">{labels[run.status]}</p>
    <Badge variant={qualityStatusVariant(run.quality_status)} label={qualityStatusLabel(run.quality_status)}/>
    <p>{awaiting ? run.apply_allowed ? "참조 규칙이 만든 참조 분류예요. 반영하면 근거 지도에 그대로 들어가요." :
      "이 분류는 모델이 아니라 참조 규칙이 만든 것이에요. 위키에 반영되지 않아요." : "이 실행은 참조 규칙으로 분류해요."}</p>
    <p>대상 실적 · {run.project_id}<br/>원본 파일 · {run.source_filename} ({fileSize(run.source_size_bytes)}, {mediaNames[run.source_media_type] ?? run.source_media_type})<br/>
      요구사항 수 · {wikiValue(run.requirement_count)}<br/>접수 · {run.created_by_name} · {formatDateTime(run.created_at)}</p>
    {run.decided_at && <p>검토 결정 · {wikiValue(run.decided_by_name)} · {formatDateTime(run.decided_at)}</p>}
    {run.status === "rejected" && <p>반려 사유 · {wikiValue(run.decision_reason)}</p>}
    {run.error_code && <IngestProblem code={run.error_code} fallback="실적 넣기 작업을 마치지 못했어요."/>}
    {(awaiting || run.assignments.length > 0) && <Review run={run}/>}
    {awaiting && <>
      <div className="wiki-actions">
        <Button label="위키에 반영" isDisabled={!run.apply_allowed || decision.isPending} onClick={() => {
          if (checkName()) { decision.reset(); setAction("approve"); }
        }}/>
        <Button label="반려" isDisabled={decision.isPending} onClick={() => {
          if (checkName()) { decision.reset(); setReason(""); setAction("reject"); }
        }}/>
      </div>
      {needsName && !actor && <p role="status">사이드바에 담당자 이름을 입력해 주세요.</p>}
      <CriteriaDialog open={dialogOpen} title={action === "approve" ? "위키에 반영" : "실적 넣기 반려"}
        onClose={() => { if (!decision.isPending) setAction(null); }}>
        <p>{run.project_title} · {run.source_filename}</p><p>담당자 · {actor}</p>
        {action === "approve" ? <p>위키를 고치기 전에 사본을 남겨요.</p> :
          <label className="wiki-dialog-field">반려 사유<textarea value={reason} maxLength={1000} disabled={decision.isPending}
            onChange={event => setReason(event.target.value)}/></label>}
        {dialogOpen && decision.error && <IngestProblem error={decision.error}/>}
        <DialogActions><CancelButton isDisabled={decision.isPending} onClick={() => setAction(null)}/>
          <Button label={action === "approve" ? "반영 확인" : "반려 확인"}
            isDisabled={decision.isPending || (action === "approve" ? !run.apply_allowed : !reason.trim())}
            onClick={() => { if (checkName()) decision.mutate(action === "approve" ? null : reason.trim()); }}/>
        </DialogActions>
      </CriteriaDialog>
    </>}
    {!dialogOpen && decision.error && <IngestProblem error={decision.error}/>}
    {run.status === "applied" && <>
      <h3>위키 반영 기록</h3>
      <p>반영 시각 · {formatDateTime(run.applied_at)}</p>
      <TechnicalInfo summary="기술 정보"><p>반영 전 · {run.wiki_sha256_before?.slice(0, 12) ?? "값 없음"}<br/>
        반영 후 · {run.wiki_sha256_after?.slice(0, 12) ?? "값 없음"}<br/>사본 이름 · {wikiValue(run.backup_name)}</p></TechnicalInfo>
      <Link to={wikiUrl("work-units")}>업무별 근거 지도 보기</Link>
    </>}
  </>;
}

export function WikiIngests({ items, total, offset, selection }: {
  items: IngestSummary[]; total: number; offset: number; selection: string | null;
}) {
  const selected = selection ?? items[0]?.id ?? null;
  const url = (start: number, run?: string) => wikiUrl("ingests", {
    ...(start ? { offset: String(start) } : {}), ...(run ? { run } : {}),
  });
  return <WikiSplit selected={selected} list={<>
    {!items.length && <p>넣기 기록이 없어요.</p>}
    {items.map(item => <Link key={item.id} to={url(offset, item.id)} aria-current={item.id === selected ? "page" : undefined}>
      <strong>{item.project_title}</strong><small>실적 {item.project_id}</small><span>{item.source_filename}</span>
      <span>{labels[item.status]} · 요구사항 {item.requirement_count === null ? "값 없음" : item.requirement_count + "건"}</span><span>{formatDateTime(item.created_at)}</span>
    </Link>)}
    {(offset > 0 || offset + ingestLimit < total) && <nav aria-label="넣기 기록 페이지">
      {offset > 0 && <Link to={url(Math.max(0, offset - ingestLimit))}>이전 기록</Link>}
      {offset + ingestLimit < total && <Link to={url(offset + ingestLimit)}>다음 기록</Link>}
    </nav>}
  </>}>{selected && <RunDetail key={selected} id={selected}/>}</WikiSplit>;
}
