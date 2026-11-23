# 2026-11-23 회사 위키 넣기 — 격리 스택 시운전

회사 근거 화면의 위키 보기와 실적 넣기(참조 분류)를 실제 컨테이너 스택에서 한 번 끝까지 돌린 기록이다.
결과는 `mock_reference`이며 품질·운영 활성화 근거가 아니다. 운영 스택과 운영 위키는 건드리지 않았다.

## 구성

- 코드: 이 브랜치(`wiki-ingest`). 앱 이미지는 `bidops-wikitrial:app` — 현재 운영 web 이미지 위에 이 브랜치의 백엔드·엔진 패키지·스크립트·프런트엔드 빌드를 덮어 만든 시운전용 이미지다(정식 빌드가 아니다). 문서 worker는 기존 `bidops:document-arm64-main-20261118`.
- 스택: `COMPOSE_PROJECT_NAME=bidops-wikitrial BIDOPS_ENV=mock scripts/compose.sh …`, web `127.0.0.1:18795`. postgres·minio·clamav·document-worker(1개)·web·analysis-worker.
- 설정(`env/mock.env`, Git 밖): 개발용 자격에 `BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG=rootlab`, `BIDOPS_COMPANY_WIKI_INGEST_ENABLED=true`, `BIDOPS_COMPANY_WIKI_INGEST_APPLY_REFERENCE_ENABLED=true`, `BIDOPS_COMPANY_WIKI_BACKUP_DIR=/app/company-wiki-backups`, 넣기 전용 객체 저장소 키.
- 위키: 운영 정본(`/Users/temp/orca/bidops/wiki`)의 **사본**을 이 복제본의 `wiki/`에 두고 붙였다. 시운전이 고친 것은 이 사본뿐이다.
- 초기화: `postgres-init` → `migrate`(0043 포함) → `minio-init`(넣기 버킷과 전용 정책).

## 한 일과 결과

| 단계 | 결과 |
|---|---|
| 상태 점검 | `/api/health` 200 |
| 위키 조회 | `/api/company-wiki` — ㈜루트랩, 실적 58, 넣은 사업 23, 단위 263, 근거 연결 3,969, 묶음 digest `54b2292ee207…`(엔진 계산값과 같음) |
| 업로드 | 소방안전 2025 사전규격 HWP(278,016바이트)를 P2025-08로 올림 → 202 `queued` |
| 추출·분류 | 약 10초 뒤 `awaiting_review`. 실제 ClamAV 검사와 문서 worker 변환을 거쳐 요구사항 70건, 목록에 없는 번호 1개, 미분류 10건, `mock_reference` |
| 승인 | 200 `approved` → `applying` → 약 6초 뒤 `applied` |
| 사본 | `backups/company-wiki/20261123T102044353284Z-43e0c921/`에 YAML 세 파일과 위키 폴더 |
| 위키 변화 | digest `54b2292ee207…` → `fbff316dbf63…`, `log.txt`에 `ingest | P2025-08 | 요구사항 70건, 미분류 10건`, 실적 페이지의 요구사항 목록은 글자 변화 없음(이미 같은 내용) |
| 운영 정본 | 변화 없음(사본과 정본을 비교해 바뀐 파일이 사본 쪽 근거 지도 페이지뿐임을 확인) |
| 거절 경로 | 허용 밖 확장자 422 `unsupported_extension`, 미등록 실적 422 `project_not_registered`, 담당자 이름 없음 400 `actor_name_required` |
| 화면(실제 서버, 가짜 응답 없음) | 브라우저로 `/company`의 개요·실적·넣기 기록을 열고, 실적 보기에서 "실적 넣기"로 맞춤배움길 2024 사전규격 HWP를 P2023-12에 올림 → 넣기 기록 보기로 이동 → `검토 대기`, 요구사항 57건, "위키에 반영"·"반려" 단추 표시 |

## 확인된 점

- 업로드부터 위키 반영까지의 흐름이 가짜 변환기·가짜 API 없이 실제 스택에서 돈다.
- 참조 분류의 품질은 예상대로 낮다. 근거 연결이 3,969건에서 3,828건으로 줄었다(P2025-08의 모델 분류 연결이 참조 분류로 바뀜). "장애 조치" 요구사항이 미분류로 남는 등 내용도 맞지 않는다. 참조 분류 결과의 반영을 기본으로 꺼 둔 이유가 그대로 드러난다.

## 시운전에서 걸린 것

- Docker 네트워크 주소 풀이 가득 차 스택 네트워크를 만들지 못했다. 2026-11-18에 종료한 데모 스택(`bidops-local`)의 쓰지 않는 네트워크 11개를 지워 해결했다(컨테이너 0개인 것만, 볼륨은 그대로).
- 화면 검사를 돌릴 때 기본 미리보기 포트(4173)를 다른 세션이 쓰고 있었다. `PW_PORT`를 따로 줘야 이 브랜치의 빌드를 본다.

## 남은 상태

- 스택은 떠 있다(`http://127.0.0.1:18795/company`). P2023-12 실행 1건이 `검토 대기`로 남아 있다(2023년 실적에 2024년 문서를 올린 시험용이다).
- 내리는 법: `COMPOSE_PROJECT_NAME=bidops-wikitrial BIDOPS_ENV=mock scripts/compose.sh down` (볼륨까지 지우려면 사람이 확인하고 따로).

## 하지 않은 것

- 정식 이미지 빌드, 운영 배포, 운영 DB migration.
- 실제 모델 분류.
- 반영 실패 복구를 실제 스택에서 유발해 보는 것(자동 검사에서만 확인했다).
