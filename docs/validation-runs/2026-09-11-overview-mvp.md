# 2026-09-11 사전규격 개요 MVP 첫 실사용 실행

실행 기록이다. 계약·규칙의 정본은 `contracts.md`·`business-rules.md`이며 이 문서는 그것을 대체하지 않는다.
결과는 참조 실행이고 품질 승인·정책 활성화의 근거가 아니다.

## 코드·배포

- main `8eeae7c` (P0 배관 → P1 철거 → P2 runner → P3 화면 → P4 자격 완화·backfill → P5 첫 실행 원인 수정 → P6 부분 완료 규칙).
- 이미지 `bidops-overview-mvp:20260911`(마지막 빌드는 `8eeae7c`), migration head `0026_overview_mvp`.
- 배포 설정 `~/.local/state/bidops/deployments/overview-mvp-20260911-01605066/`
  (`deploy.compose.json` web, `document-worker.image.json`, `prespec-attachment-worker.compose.json`,
  `analysis-worker.compose.json`, `migrate.image.json`). analysis-worker json에는 base compose에 없던
  source·structure·quarantine MinIO 키, `scanning` 네트워크, ClamAV env, `document-scratch:/scratch`,
  `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`를 넣었다(P5에서 base compose에도 반영).
- 모델: `qwen3.8-27B` @ `http://192.168.0.139:58765/v1`, 보고 revision `5fa804ff…`, `max_model_len` 262,144.

## 데이터

- 운영 DB 초기화(2026-09-11 14:08 KST): 전체 스키마 pg_dump `backups/bidops-full-pre-reset-20260911.dump` 뒤 keep-list
  (`alembic_version`, `analysis_policy_version`, `profile_version`, `profile_evidence`, `company_profile_snapshot`,
  `order_plan_screening_policy`, `screening_policy`, `schedule_setting`) 밖 TRUNCATE CASCADE. CASCADE가
  `profile_evidence`·`screening_policy`까지 지워 dump에서 복구했고, MinIO 정리 때 프로필 근거 객체 2개가 함께 지워져
  같은 바이트를 재업로드한 뒤 `content_object_location.object_version_id`를 갱신했다. MinIO 4 bucket 객체 1,112개 삭제.
- 새 수집: 발주계획 `data/runs/order-plans-20260910-20260911` 482건(complete), 사전규격
  `data/runs/prespecs-20260910-20260911` 342건(SW=Y 33, 첨부 516, complete). 적재는
  `select_validation_sample.py --analysis-count 342 --audit-count 294`로 전 건 선택 파일을 만든 뒤 `ingest.cli --run`.
  적재 뒤 첨부 자격은 `refresh_fetch_eligibility`를 web 컨테이너에서 수동 호출(42행).
- 첨부 취득: 완료 37, 차단 5(`unsupported_extension` 3, `unsafe_document` 2). 묶음 ready 28.

## 실행 경과 (개요 run)

| 시각(UTC) | 조치 | 결과 |
|---|---|---|
| 05:20 | 첫 backfill 27건 | 전부 즉시 `runner_failed` — analysis-worker에 source/structure MinIO 키 없음 |
| 05:21 | 키 추가 후 재등록 | `pdf_preparation_failed:clamav_unavailable` — `scanning` 네트워크 없음 |
| 05:22 | 네트워크 추가 | `converter_unavailable`(≈285초) — `/scratch` 볼륨 미마운트 |
| 05:32 | 볼륨 추가 | `pdf_preparation_failed`(10~30초) — runner가 structure 저장소를 읽기 전용 자격으로 염(`482e040` 수정) |
| 05:37 | 수정 배포, 첫 실제 5건 | needs_human_review 4, `input_capacity_exceeded` 1 (아래 원인) |
| 06:0x | P5 수정 배포, 6건 | completed 2, needs_human_review 4 |
| 06:33 | 사용자 지시로 중지 | queued 10 취소, 실행 중 1건 완료 후 worker 정지 |
| 07:1x | P6 배포·재개 | 2건 완료 뒤 사용자 지시로 다시 중지(queued 19 취소) |

첫 실제 실행에서 드러난 원인과 반영한 수정:
1. 2단 레이아웃 쪽 텍스트(좌·우 열이 줄마다 번갈아 나옴) → 인용 조각 매칭(`evidence_fragment_match` 경고).
2. `- 목  차 -` 표기의 목차 쪽에서 장 제목을 잡아 1쪽 범위 → TOC 판정 보강, 2쪽/1,500자 미만이면 `range_too_small` → fallback.
3. 자동 범위 p3–78(76쪽) → `range_clipped_to_limit`로 60쪽까지 잘라 실행.
4. 모델이 주장을 전부 `business_overview`에 넣어 `required_fact_missing` → 프롬프트 섹션 지시 + 경고화.
5. 12개 중 1~2개만 `quote_not_found`이거나 unknown 6개만 `contradicted`인 run이 통째로 사람 검토 →
   실패 주장 제외·절반 게이트(`claims_dropped`), unknown 판정은 경고(`unknown_contradicted`·`unknown_insufficient`).

## 최종 집계 (07:20 UTC, `scripts/validation/overview_funnel.py`)

사전규격 342 → 자격 33 → 첨부 완료 28 → 묶음 ready 28 → run 27. 공고별 최신 run: completed 8, cancelled 19
(재등록 뒤 중지된 것이며 그 이전 시도는 needs_human_review 14·failed 66이 이력에 남아 있다. failed 66은 위 환경
문제의 반복 시도다). 심층 검토 자동 시작 0(회사 핏 게이트, ADR-0049).

완료 8건: 자동 범위 6(3~18쪽, 99~129초, 호출 2회), fallback 2(1~45·1~60쪽, 126·178초). 경고는 전부 수치·용어 대조
계열(`quantity_*`, `latin_term_mismatch`, `analysis_premise_unverified`)이며 제외 주장 0건.

## 남은 것

- 취소된 19건은 `prepare-overviews --all-eligible`로 재등록하면 새 규칙으로 다시 돈다.
- ingest CLI가 첨부 자격 hook을 부르지 않는 문제, `attachment.name` 자리표시자 문제는 `tracking/findings.md`.
- base compose와 배포 json의 이중 관리, 회사 핏 게이트로 자동 심층 검토 0건은 결정 대기.
