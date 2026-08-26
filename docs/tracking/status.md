# 구현·검증 현황

기준일: 2026-08-26

## 코드 상태

| 영역 | 현재 상태 | 근거 |
|---|---|---|
| 수집·후보·다섯 관점 판정·보고 | 구현됨 | `bidops.*.v2` 계약, 회차 산출물, pipeline/backend 테스트 |
| PostgreSQL 정본과 SQLite 이관 | 구현됨, 실제 백업본 리허설 미수행 | PostgreSQL 17 `bidops` schema, Alembic, 13개 legacy table import/reconciliation 코드 |
| MinIO·ClamAV·문서 격리 | 구현됨, 실제 운영 권한 검증 미수행 | 목적별 bucket/credential, clean scan, `document-worker network_mode:none`, object hash/location |
| 단계 B document bundle | 구현됨 | 7개 bundle/document API, HWP/HWPX/PDF 검사·구조화, immutable ready snapshot |
| 단계 C Qwen deep review | 구현됨 | 세 stage, bounded chunk/retry, fenced job, encrypted raw response, report/validation/evidence API |
| React 심층 검토 화면 | 핵심 조회·리포트 검토 구현됨 | ready bundle 선택, review 시작, report/revision/final opinion 화면과 기능 테스트 |
| Qwen 품질 activation gate | 계산·import 연결 구현됨, 실제 품질 증적 없음 | human-adjudicated scorer, 0.80/0.70/0.10 gate, policy SHA 일치 import |
| B→C 연속 인수 실행기 | 구현됨, 실제 서비스 실행 미수행 | upload→confirm→review→3 stages→validation→evidence 실행기와 dry-run/target 확인 |
| 원격 vLLM 연결 | SDK 스모크 통과, artifact 고정 미완료 | OpenAI-compatible SDK, remote IP egress override, exact base URL/model allowlist |
| 백업·복구 자동화 | 구현됨, 실제 snapshot 복구 훈련 미수행 | object-first restore, PostgreSQL restore, active hash 검증 script |

## 2026-08-26 검증 결과

- backend 전체: `278 passed, 4 skipped` (`/app/web/data`만 tmpfs인 read-only source container)
- skip 4개: 별도 격리 T7 MinIO가 필요한 live integration test
- vLLM policy/client/prompt 경계 집중 검증: `31 passed`
- 실제 vLLM SDK Stage 1: `qwen3.8-27B` non-thinking, 25.29초, prompt 531/completion 853 tokens, supported claim 2/evidence 1, 권위 validator 통과
- Compose config: base+remote vLLM 조합 유효
- 운영 DB, 기존 Compose project/volume, 실제 MinIO object는 변경하지 않음

frontend 파일은 이번 변경에서 수정하지 않았다. 기존 기능 테스트는 통과 상태이나 28개 시각 snapshot은 실행 환경의 한글 font 차이가 남아 있다.

## 배포 후보 승격 전 남은 P0

1. 현재 원격 vLLM의 image digest와 `Qwen/Qwen3.8-27B` immutable revision/artifact digest를 고정하고 대표 HWP/PDF·55개 요구사항 gold로 실제 품질 manifest를 만든다.
2. scorer 통과 결과로 measured profile/policy를 import하고 active UUID를 격리 web에 배포한다.
3. 새 Compose project에서 [단계 B→C 연속 인수 테스트](../e2e-bc-acceptance.md)를 실행해 실제 증적을 보관한다.
4. 운영 SQLite가 아닌 백업 복사본으로 13개 table row/PK/FK, 리뷰·첨부 metadata, PostgreSQL sequence, 실패 후 재실행, SQLite write 차단을 리허설한다.
5. secret manager·MinIO 권한·remote model egress firewall·복구 순서·RPO/RTO·UID/GID를 실제 배포 환경에서 검증한다.
6. 고정 Playwright image/font에서 snapshot을 재생성하고 사람이 28개 변경 이미지를 승인한다.
7. 위 P0 증적이 통과한 뒤 원격 push, main PR, migration/Compose/security review, merge, Lean v1 tag를 진행한다.

현재 상태는 “vLLM SDK 연결과 단건 실제 호출 확인”이며, 전체 B→C 서비스 E2E와 사람 품질 gate를 통과한 배포 후보는 아니다.
