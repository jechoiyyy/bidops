import { useQuery } from "@tanstack/react-query";
import { Badge } from "../common/Badge";
import { Panel } from "../common/Panel";
import { api } from "../../lib/api";
import { formatDateTime, present } from "../../lib/format";
import type { AttachmentResponse } from "../../lib/types";

interface AttachmentPanelProps {
  noticePk?: number;
  attachments: AttachmentResponse[];
  documentPreparationHref?: string;
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

function extractHistoryLabel(status: string | null): string {
  if (status === "completed") return "legacy 본문 추출 기록 완료";
  if (status === "pending") return "legacy 본문 추출 기록 대기";
  if (status === "failed") return "legacy 본문 추출 기록 실패";
  return "legacy 본문 추출 기록 미확인";
}

function sourceLabel(origin: string | null): string {
  if (origin === "manual") return "기존 수동 등록 이력";
  if (origin === "g2b") return "나라장터 제공 이력";
  return "출처 미확인";
}

function AttachmentRow({
  attachment,
}: {
  attachment: AttachmentResponse;
}) {
  return (
    <div className="attachment-row">
      <span className="attachment-ext">{extension(attachment)}</span>
      <span className="attachment-name">
        <span>{present(attachment.name, "파일명 미확인")}</span>
        <span className="attachment-meta">
          {sourceLabel(attachment.origin)} · {formatBytes(attachment.size_bytes)} · {formatDateTime(attachment.created_at)}
        </span>
        <span className="attachment-meta">{extractHistoryLabel(attachment.extract_status)} · ready bundle 판단에 사용하지 않음</span>
      </span>
      <Badge label="읽기 전용 이력" variant="neutral" />
    </div>
  );
}

export function AttachmentPanel({ noticePk, attachments, documentPreparationHref }: AttachmentPanelProps) {
  const attachmentQuery = useQuery({
    queryKey: ["notice-attachments", noticePk],
    queryFn: () => api.getNoticeAttachments(noticePk as number),
    enabled: noticePk !== undefined,
    staleTime: 0,
  });

  const procedure = attachmentQuery.data;
  const currentAttachments = procedure?.attachments ?? attachments;
  const statusLabel = currentAttachments.length > 0 ? `읽기 전용 이력 ${currentAttachments.length}건` : "읽기 전용 이력 없음";

  return (
    <Panel
      className="notice-attachments-panel"
      title="기존 첨부 출처 이력"
      action={<Badge label={statusLabel} variant="neutral" />}
    >
      <div className="attachment-status-line">
        <span>legacy 첨부 provenance를 조회하는 영역입니다. 문서 준비 완료나 심층 검토 가능 상태를 뜻하지 않습니다.</span>
        {procedure?.agency ? <span className="attachment-agency">{procedure.agency}</span> : null}
      </div>

      {currentAttachments.length > 0 ? (
        <div className="attachment-list" aria-label="기존 첨부 출처 이력">
          {currentAttachments.map((attachment) => <AttachmentRow key={attachment.id} attachment={attachment} />)}
        </div>
      ) : (
        <p className="attachment-empty">조회할 기존 첨부 provenance가 없습니다.</p>
      )}

      <div className="attachment-safe-guidance">
        <strong>다음 행동 · 안전한 문서 bundle 준비</strong>
        <p>legacy 첨부 이력은 심층 검토 입력으로 사용할 수 없습니다. 원문 격리, 악성코드 검사, 변환·구조화, 문서 역할 확인을 거쳐 ready bundle을 명시적으로 확정하십시오.</p>
        {documentPreparationHref ? (
          <a href={documentPreparationHref}>문서 준비 상태 확인</a>
        ) : (
          <span>공고 상세의 문서 준비 영역에서 ready bundle 상태를 확인하십시오.</span>
        )}
      </div>
    </Panel>
  );
}
