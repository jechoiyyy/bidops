import { ApiError } from "../../lib/api";

const messages: Record<string, string> = {
  actor_name_required: "사이드바에 담당자 이름을 입력해 주세요.",
  actor_name_invalid: "사이드바의 담당자 이름을 확인해 주세요.",
  company_wiki_ingest_disabled: "실적 넣기는 아직 켜지지 않았어요.",
  not_found: "넣기 기록을 찾을 수 없어요.",
  company_wiki_unavailable: "회사 위키가 아직 연결되지 않았어요.",
  company_wiki_unreadable: "회사 위키를 읽을 수 없어요.",
  idempotency_conflict: "같은 요청 번호에 다른 입력이 있어요. 파일을 다시 선택해 주세요.",
  ingest_in_progress: "이 실적에 진행 중인 실행이 있어요. 넣기 기록을 확인해 주세요.",
  status_conflict: "실행 상태가 바뀌었어요. 현재 상태를 확인해 주세요.",
  reference_apply_disabled: "이 환경에서는 참조 분류를 위키에 반영할 수 없어요.",
  input_size_limit: "파일이 업로드 크기 제한을 넘었어요.",
  invalid_request: "요청 값을 확인해 주세요.",
  project_not_registered: "등록된 실적을 찾을 수 없어요.",
  unsupported_extension: "HWP, HWPX 또는 PDF 파일을 선택해 주세요.",
  mime_mismatch: "파일 내용과 형식이 일치하지 않아요.",
  storage_unavailable: "원본 저장소에 연결할 수 없어요.",
  ingest_unavailable: "지금은 실적 넣기를 처리할 수 없어요.",
  portfolio_page_missing: "대상 실적 페이지가 없어요.",
  no_requirements: "문서에서 요구사항을 추출하지 못했어요.",
  malware_detected: "악성코드가 발견돼 파일을 차단했어요.",
  clamav_unavailable: "악성코드 검사기에 연결할 수 없어요.",
  converter_unavailable: "문서 변환기에 연결할 수 없어요.",
  timeout: "제한 시간 안에 처리를 마치지 못했어요.",
  hash_mismatch: "원본 파일의 해시가 일치하지 않아요.",
  engine_process_failed: "분석 엔진이 처리를 마치지 못했어요.",
  processing_failed: "문서를 처리하지 못했어요.",
  backup_dir_unset: "위키 사본을 저장할 폴더가 설정되지 않았어요.",
  unsafe_backup_dir: "설정된 폴더에 위키 사본을 안전하게 저장할 수 없어요.",
  unsafe_wiki_bundle: "회사 위키 묶음을 안전하게 처리할 수 없어요.",
  apply_failed: "반영에 실패해 사본에서 위키를 복구했어요.",
  lease_expired: "작업자의 응답이 오래 없어 실행을 중단했어요.",
};

export function IngestProblem({ error, code, fallback = "실적 넣기 요청을 처리하지 못했어요." }: {
  error?: Error | null; code?: string | null; fallback?: string;
}) {
  const key = code ?? (error instanceof ApiError ? error.code : null);
  return <p role="alert">{(key && messages[key]) || fallback}{key && <> (<code>{key}</code>)</>}</p>;
}
