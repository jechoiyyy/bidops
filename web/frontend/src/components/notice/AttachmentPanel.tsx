import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge } from "../common/Badge";
import { Panel } from "../common/Panel";
import { api } from "../../lib/api";
import { present } from "../../lib/format";
import type { AttachmentProcedureResponse, AttachmentResponse } from "../../lib/types";

interface AttachmentPanelProps {
  noticePk?: number;
  attachments: AttachmentResponse[];
}

function extension(attachment: AttachmentResponse): string {
  if (attachment.file_ext?.trim()) return attachment.file_ext.toUpperCase();
  const name = attachment.name?.split(".").pop();
  return name && name !== attachment.name ? name.toUpperCase() : "파일";
}

function formatBytes(value: number | null): string {
  if (value === null || value === undefined) return "크기 미확인";
  if (value < 1024) return `${value}B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)}KB`;
  return `${(value / (1024 * 1024)).toFixed(1)}MB`;
}

function extractLabel(status: string | null): string {
  if (status === "completed") return "본문 추출 완료";
  if (status === "pending") return "본문 추출 대기";
  if (status === "failed") return "본문 추출 실패";
  return "본문 추출 미확인";
}

function inferStatus(attachments: AttachmentResponse[]): AttachmentProcedureResponse["status"] {
  if (attachments.some((item) => item.origin === "manual")) return "completed";
  if (attachments.length > 0) return "provided";
  return "missing";
}

function sourceLabel(origin: string | null): string {
  if (origin === "manual") return "출처 manual";
  if (origin === "g2b") return "출처 나라장터";
  return "출처 미확인";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "파일 등록에 실패했습니다.";
}

function AttachmentRow({
  attachment,
  onDelete,
  deleting,
}: {
  attachment: AttachmentResponse;
  onDelete?: (attachment: AttachmentResponse) => void;
  deleting: boolean;
}) {
  return (
    <div className="attachment-row">
      <span className="attachment-ext">{extension(attachment)}</span>
      <span className="attachment-name">
        <span>{present(attachment.name, "파일명 미확인")}</span>
        <span className="attachment-meta">{formatBytes(attachment.size_bytes)} · {sourceLabel(attachment.origin)}</span>
      </span>
      <Badge
        label={extractLabel(attachment.extract_status)}
        variant={attachment.extract_status === "completed" ? "evidence-confirmed" : "neutral"}
      />
      {attachment.url ? (
        <a className="attachment-link" href={attachment.url} target="_blank" rel="noreferrer" aria-label={`${present(attachment.name, "첨부 문서")} 내려받기`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
          </svg>
        </a>
      ) : null}
      {attachment.origin === "manual" && onDelete ? (
        <button className="attachment-delete" type="button" disabled={deleting} onClick={() => onDelete(attachment)} aria-label={`${present(attachment.name, "첨부 문서")} 삭제`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M5 7h14M10 11v6M14 11v6M8 7l1-3h6l1 3M7 7l1 14h8l1-14" />
          </svg>
        </button>
      ) : null}
    </div>
  );
}

function UploadDropzone({
  disabled,
  onFiles,
}: {
  disabled: boolean;
  onFiles: (files: FileList | File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const chooseFiles = () => inputRef.current?.click();
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if ((event.key === "Enter" || event.key === " ") && !disabled) {
      event.preventDefault();
      chooseFiles();
    }
  };

  return (
    <div
      className={`attachment-dropzone ${dragging ? "is-dragging" : ""}`.trim()}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      onClick={chooseFiles}
      onKeyDown={handleKeyDown}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) onFiles(event.dataTransfer.files);
      }}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
      </svg>
      <strong>확보한 문서를 여기에 놓거나 선택합니다</strong>
      <span>HWP · HWPX · PDF · 파일당 50MB</span>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        multiple
        accept=".hwp,.hwpx,.pdf"
        disabled={disabled}
        onChange={(event) => {
          if (event.target.files) onFiles(event.target.files);
          event.currentTarget.value = "";
        }}
      />
    </div>
  );
}

export function AttachmentPanel({ noticePk, attachments }: AttachmentPanelProps) {
  const queryClient = useQueryClient();
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const attachmentQuery = useQuery({
    queryKey: ["notice-attachments", noticePk],
    queryFn: () => api.getNoticeAttachments(noticePk as number),
    enabled: noticePk !== undefined,
    staleTime: 0,
  });

  const procedure = attachmentQuery.data;
  const currentAttachments = procedure?.attachments ?? attachments;
  const status = procedure?.status ?? inferStatus(currentAttachments);
  const statusLabel = status === "provided" ? `나라장터 제공 ${currentAttachments.length}건` : status === "completed" ? `확보 완료 ${currentAttachments.length}건` : "나라장터 미제공";
  const statusVariant = status === "provided" || status === "completed" ? "grade-2" : "neutral";

  const uploadFiles = async (files: FileList | File[]) => {
    if (noticePk === undefined || files.length === 0) return;
    setUploadError(null);
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await api.uploadNoticeAttachments(noticePk, file);
      }
      await queryClient.invalidateQueries({ queryKey: ["notice-attachments", noticePk] });
      await queryClient.invalidateQueries({ queryKey: ["notice", noticePk] });
    } catch (error) {
      setUploadError(errorMessage(error));
    } finally {
      setUploading(false);
    }
  };

  const deleteAttachment = async (attachment: AttachmentResponse) => {
    if (!window.confirm(`${present(attachment.name, "이 첨부 문서")}를 삭제하시겠습니까?`)) return;
    setDeleting(true);
    setUploadError(null);
    try {
      await api.deleteAttachment(attachment.id);
      await queryClient.invalidateQueries({ queryKey: ["notice-attachments", noticePk] });
      await queryClient.invalidateQueries({ queryKey: ["notice", noticePk] });
    } catch (error) {
      setUploadError(errorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Panel
      className="notice-attachments-panel"
      title="첨부 문서 확보"
      action={<Badge label={statusLabel} variant={statusVariant} />}
    >
      <div className="attachment-status-line">
        <span>{status === "provided" ? "나라장터가 제공한 원문입니다." : status === "completed" ? "담당자가 등록한 문서가 원문 보관소에 저장되었습니다." : "나라장터에 첨부가 없어 발주기관 시스템에서 확보해야 합니다."}</span>
        {procedure?.agency ? <span className="attachment-agency">{procedure.agency}</span> : null}
      </div>

      {status !== "provided" ? (
        <div className="attachment-workflow-grid">
          <div className="attachment-procedure">
            <div className="attachment-section-label">확보 절차</div>
            {(procedure?.steps.length ? procedure.steps : [
              "발주기관의 자체 조달시스템을 확인합니다.",
              "해당 시스템에서 공고번호 또는 공고명으로 입찰공고를 검색합니다.",
              "상세 공고의 첨부파일을 내려받아 애플리케이션에 등록합니다.",
            ]).map((step, index) => (
              <div className="attachment-step" key={step}>
                <span className="attachment-step-number">{index + 1}</span>
                <div>
                  <strong>{step}</strong>
                  {index === 0 ? (
                    <p>
                      {procedure?.matched_portal && procedure.search_url ? (
                        <a className="attachment-portal-link" href={procedure.search_url} target="_blank" rel="noreferrer">{present(procedure.matched_portal.system_name, "조달시스템")} 검색 주소 열기</a>
                      ) : (
                        <>
                          <span className="attachment-no-portal">등록된 조달시스템 없음</span>{" "}
                          <Link to={`/attachments${noticePk ? `?notice=${noticePk}${procedure?.agency ? `&agency=${encodeURIComponent(procedure.agency)}` : ""}` : ""}`}>기관 등록 경로 열기</Link>
                        </>
                      )}
                    </p>
                  ) : index === 1 ? (
                    <p>검색어 {present(procedure?.bid_no, "공고명으로 검색")} · {present(procedure?.title, "공고명 미확인")}</p>
                  ) : (
                    <p>제안요청서·과업내용서 등 검토에 필요한 파일을 등록합니다.</p>
                  )}
                </div>
              </div>
            ))}
            {procedure?.portal_message ? <p className="attachment-portal-message">{procedure.portal_message}</p> : null}
          </div>

          <div className="attachment-upload-column">
            <div className="attachment-section-label">확보 문서 {currentAttachments.length > 0 ? `· ${currentAttachments.length}건` : "· 미등록"}</div>
            {currentAttachments.length > 0 ? (
              <div className="attachment-list">
                {currentAttachments.map((attachment) => <AttachmentRow key={attachment.id} attachment={attachment} onDelete={deleteAttachment} deleting={deleting} />)}
              </div>
            ) : null}
            <UploadDropzone disabled={uploading || noticePk === undefined} onFiles={(files) => void uploadFiles(files)} />
            {uploading ? <p className="attachment-upload-status">파일을 등록하는 중입니다.</p> : null}
            {uploadError ? <p className="attachment-upload-error" role="alert">{uploadError}</p> : null}
          </div>
        </div>
      ) : (
        <div className="attachment-list">
          {currentAttachments.map((attachment) => <AttachmentRow key={attachment.id} attachment={attachment} deleting={deleting} />)}
        </div>
      )}
      {status === "provided" && currentAttachments.length === 0 ? <p className="attachment-empty">파일 목록을 확인할 수 없습니다.</p> : null}
    </Panel>
  );
}
