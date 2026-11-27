import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { DialogHeader } from "@astryxdesign/core/Dialog";
import { Dialog } from "../common/WorkspaceDialog";
import { Facts } from "../common/Facts";
import { StatusMark } from "../common/Marks";
import { engineReviewApi, type EngineReviewPreview } from "../../lib/engineReviewApi";
import { engineReviewErrorCode, engineReviewReason } from "../../lib/engineReviewCopy";
import { generateRequestId } from "../../lib/requestId";
import { refreshEngineReview } from "../../lib/useEngineReview";
import "../../styles/bulk-dialog.css";

const kst = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Seoul",
  hourCycle: "h23",
});

function pages(start: number | null, end: number | null) {
  if (start === null && end === null) return "쪽 범위 미확인";
  if (start === end) return `${start}쪽`;
  return `${start ?? "미확인"}–${end ?? "미확인"}쪽`;
}

function WikiPages({ label, slugs }: { label: string; slugs: string[] }) {
  if (slugs.length === 0) return null;
  const list = <ul aria-label={label}>{slugs.map((slug) => <li key={slug}>{slug}</li>)}</ul>;
  return slugs.length > 10 ? (
    <details className="engine-review-preview-details">
      <summary>{label} {slugs.length}개 보기</summary>
      {list}
    </details>
  ) : (
    <div className="engine-review-preview-details">
      <p>{label}</p>
      {list}
    </div>
  );
}

function PreviewFacts({ preview }: { preview: EngineReviewPreview }) {
  const { manifest } = preview;
  const sections = manifest.sections;
  const allRangesUnknown = sections.every((section) => section.page_start === null && section.page_end === null);
  return (
    <>
      <StatusMark
        className="engine-review-preview-mode"
        mark={{
          label: manifest.mode === "mock_reference" ? "모의 실행이에요. 외부로 전송하지 않아요." : "실제 전송이에요.",
          tone: "neutral",
        }}
      />
      <Facts fallback="미확인" items={[
        { label: "보낼 문서", value: manifest.documents.length > 0 ? (
          <ul>{manifest.documents.map((doc) => (
            <li key={doc.document_version_id}>{doc.filename} · {doc.page_count === null ? "쪽 수 미확인" : `${doc.page_count}쪽`}</li>
          ))}</ul>
        ) : null },
        { label: "회사 자료", value: (
          <>
            <span>{manifest.company_bundle_slug} · <code>{manifest.company_bundle_sha256.slice(0, 12)}</code></span>
            <p>선택한 위키 {manifest.wiki_pages.length}쪽 · 발췌 {manifest.wiki_chars.toLocaleString("ko-KR")}자 · 분량 때문에 빠진 위키 {manifest.wiki_pages_skipped.length}쪽</p>
          </>
        ) },
        { label: "수신", value: `${manifest.mode} · ${manifest.model}` },
        { label: "호출 수", value: `예정 ${manifest.planned_calls}회 · 남은 상한 ${manifest.remaining_calls}회` },
        { label: "유효 시각", value: <time dateTime={preview.expires_at}>{kst.format(new Date(preview.expires_at))} (KST)</time> },
      ]} />
      {sections.length > 0 ? (
        <details className="engine-review-preview-details">
          <summary>절 {sections.length}개 보기</summary>
          {allRangesUnknown ? <p>쪽 범위는 확인되지 않았어요</p> : null}
          <ul aria-label="절·쪽 범위">{sections.map((section) => (
            <li key={section.id}>{section.heading}{allRangesUnknown ? null : ` · ${pages(section.page_start, section.page_end)}`}</li>
          ))}</ul>
        </details>
      ) : null}
      <WikiPages label="선택한 위키 페이지" slugs={manifest.wiki_pages} />
      <WikiPages label="빠진 위키 페이지" slugs={manifest.wiki_pages_skipped} />
    </>
  );
}

export function EngineReviewPreviewDialog({ noticeId, actor, onClose }: {
  noticeId: number;
  actor: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<EngineReviewPreview | null>(null);
  const [pending, setPending] = useState<"preview" | "approve" | "dismiss" | null>("preview");
  const [problem, setProblem] = useState<ReturnType<typeof engineReviewReason> | null>(null);
  const [refreshRequired, setRefreshRequired] = useState(false);
  const [previewRequestId, setPreviewRequestId] = useState(generateRequestId);
  const loaded = useRef(false);
  const busy = useRef(false);
  const commandIds = useRef<{ approve?: string; dismiss?: string }>({});

  function report(error: unknown, fallback: string) {
    const code = engineReviewErrorCode(error);
    const stale = code === "preview_expired" || code === "input_changed";
    setRefreshRequired(stale);
    if (stale) setPreview(null);
    if (code === "tracking_required") void refreshEngineReview(queryClient, noticeId);
    setProblem(engineReviewReason(code, fallback));
  }

  async function load(requestId: string) {
    if (busy.current) return;
    busy.current = true;
    setPending("preview");
    setProblem(null);
    try {
      setPreview(await engineReviewApi.preview(noticeId, { request_id: requestId }, actor));
      setRefreshRequired(false);
      commandIds.current = {};
    } catch (error) {
      report(error, "전송 자료를 불러오지 못했어요.");
    } finally {
      busy.current = false;
      setPending(null);
    }
  }

  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    void load(previewRequestId);
  }, []);

  function reload() {
    const requestId = refreshRequired ? generateRequestId() : previewRequestId;
    setPreviewRequestId(requestId);
    void load(requestId);
  }

  async function submit(action: "approve" | "dismiss") {
    if (!preview || busy.current) return;
    busy.current = true;
    setPending(action);
    setProblem(null);
    const requestId = commandIds.current[action] ??= generateRequestId();
    const body = { preview_id: preview.preview_id, request_id: requestId };
    try {
      if (action === "approve") {
        await engineReviewApi.approve(noticeId, { ...body, manifest_sha256: preview.manifest_sha256 }, actor);
      } else {
        await engineReviewApi.dismiss(noticeId, body, actor);
      }
      onClose();
      void refreshEngineReview(queryClient, noticeId);
    } catch (error) {
      report(error, action === "approve" ? "승인을 저장하지 못했어요." : "건너뛰기를 저장하지 못했어요.");
    } finally {
      busy.current = false;
      setPending(null);
    }
  }

  function close() {
    if (pending !== "approve" && pending !== "dismiss") onClose();
  }

  return (
    <Dialog aria-label="전송 자료 확인" isOpen purpose="form" width={680} maxHeight="90dvh" onOpenChange={(open) => { if (!open) close(); }}>
      <div className="bulk-dialog engine-review-preview">
        <DialogHeader title="전송 자료 확인" subtitle={`담당자 ${actor}`} />
        <div className="bulk-dialog-body">
          {pending === "preview" ? <p role="status">전송 자료를 불러오는 중이에요.</p> : null}
          {preview ? <PreviewFacts preview={preview} /> : null}
          {problem ? <p role="alert">{problem.message} {problem.code ? <code>{problem.code}</code> : null}</p> : null}
        </div>
        <div className="bulk-dialog-footer">
          <Button label="닫기" variant="secondary" isDisabled={pending === "approve" || pending === "dismiss"} onClick={close} />
          {preview ? (
            <>
              <Button label="이번엔 보내지 않음" variant="secondary" isDisabled={pending !== null} onClick={() => { void submit("dismiss"); }} />
              <Button label="승인" variant="primary" isDisabled={pending !== null} onClick={() => { void submit("approve"); }} />
            </>
          ) : problem ? (
            <Button label="다시 불러오기" variant="primary" isDisabled={pending !== null} onClick={reload} />
          ) : null}
        </div>
      </div>
    </Dialog>
  );
}
