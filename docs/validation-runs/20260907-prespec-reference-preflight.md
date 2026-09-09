# 사전규격 실제 참조 실행 — 사전 점검

- 실행일: 2026-09-07
- 시작 코드: `2877b686e9dfe262de2c0d23171ea6247efed05f`
- 사용자 지정 입력: `data/runs/prespecs-20260831-20260902`
- 최초 범위: 사전규격 수집 결과 재사용부터 심층 보고서와 사람의 추적 결정까지.
  후속 요청으로 현재 단계는 SW Y 64건의 첨부·파싱·개요까지로 축소했다.
  [현재 범위와 프로필 점검](20260907-prespec-overview-profile-check.md)을 함께 읽는다.
- 결과 성격: 참조 실행. mock 결과와 실제 모델 결과를 구분하며 품질·운영 활성화 근거로 사용하지 않는다.

## 입력과 초기 적재

수집 파일은 `bidops.collected.v2`, 673건이며 notice ID도 673개다. 수집 경고는 0건,
후보군은 94건, 감사 모집단은 579건이다. SW사업대상은 Y 64건, N 609건이다.
첨부 메타데이터가 있는 공고는 603건이며 첨부는 총 978개다.
원본 수집 파일의 SHA-256은
`474b14b0946d4434e5407d19876578796dd1534ed1daa89f68ad9f7c5d54ce85`다.

다음 명령으로 새 `validation-set.json`을 생성했다. 기존 수집 JSON과 raw는 수정하지 않았다.

```bash
python3 skills/bidops-collect/scripts/select_validation_sample.py \
  data/runs/prespecs-20260831-20260902/collected-notices.json \
  --output data/runs/prespecs-20260831-20260902/validation-set.json
```

분석 30건·감사 10건을 선정했다. 기존 컨테이너에 동일 경로가 없음을 확인하고
`docker cp`로 회차를 복사한 뒤 `POST /api/runs/ingest`를 실행했다.
앱이 등록한 확장 hook을 사용하기 위해 REST 적재 경로를 사용했다.

- 회차 ID: `prespecs-20260831-20260902--20260906T181718.227147Z`
- 초기 DB 공고: 40건, 판정: 0건, 리뷰: 0건
- 경고: `screening_results_missing` 1건, 차단 등급 경고: 0건
- `/api/pre-specs?sw_only=false`: 40건, 기본 SW 필터: 13건

초기 적재는 전체 673건이 아니라 validation 표본 40건을 notice로 투영한다.
C-1 `full_run`은 수집본에서 정책의 `candidate_pool`을 읽어 94건을 선정하는 별도 경로다.
따라서 수집 총계·초기 적재 건수·향후 판정 대상 건수를 같은 값으로 보고하지 않는다.

## 실행 환경 준비

기존 web·PostgreSQL·MinIO·ClamAV가 healthy이고 문서·분석 worker가 실행 중이었다.
`GET /api/health`는 `{"status":"ok"}`를 반환했다. web 이미지의 `core/db.py`,
`core/model_client.py`, `lifecycle/ingest/cli.py` 해시는 host 코드와 일치했다.

```bash
docker exec bidops-web-1 python -m app.screening.policy \
  seed-default --created-by codex-prespec-reference
docker exec bidops-web-1 python -m app.deep_review.cli \
  import-profile-policy --actor codex-prespec-reference
```

- C-1: `screening-policy.v1.20260825`, `activation_candidate`. 운영 활성화는 하지 않았다.
- 프로필 ID: `d970500a-e30c-46cf-85e0-7e9a9e854f2b`
- 분석 정책 ID: `4d6b9f90-4e38-449f-9860-dc0314bd9491`
- import의 `active_configuration_changed=false`. 측정값은 제공하지 않았다.
- 별도 로컬 참조 실행 overlay의 `docker compose ... config --quiet`는 통과했다.
  아직 재기동하거나 모델 작업을 enqueue하지 않았다.

사용자가 실행 서버를 Ollama로 정정했다. 해당 서버의 `/api/tags`, `/v1/models`를
읽어 `qwen3.8:27b`와 `qwen3.8:27b-bf16` 및 각 digest가 존재함을 확인했다.
정본 개요·심층 정책의 모델명 `qwen3.8-27B`는 제공 목록에 없다.
모델 선택과 그에 맞는 정책 binding을 확정하기 전에는 본문을 전송하지 않는다.
서버 주소와 자격증명은 이 기록에 저장하지 않는다.

host 방화벽 조회는 `sudo: a password is required`로 실행되지 않았다.
모델 IP·port와 첨부 host의 egress 제한 설정 여부는 사용자에게 확인 요청했다.

## 이번에 실행한 검증

격리 workspace에서 `BIDOPS_TEST_MODE=1`과
`--extension-provider app.screening:register_lifecycle_extensions`를 지정하여
`python -m app.deep_review.cli run-prespec-e2e`를 실행했다.

- `passed=true`, 합성 공고 2건, 미지원 첨부 제외 2건
- `pre-1`: `deep_review_started`, 개요·심층 `completed`, 심층 `quality_status=mock_reference`
- `pre-5`: `deep_review_ready_for_click`, 사유 `not_sw_business`, 심층 검토 없음
- 증거: `/tmp/bidops-prespec-mock-20260907-unHsZ0/evidence.json`
- `./run-tests.sh`: collect 41, report 13, screen 89, cross 2 — 총 145건 통과
- 프론트엔드 production build 통과
- 화면 게이트: `295 passed, 5 failed, 4 skipped (7.6m)`. 실패는 마감 경로 쿼리 보존
  1건, 공통 셸 2건(두 폭), 1280px 정책·운영 화면의 제목을 찾지 못한 2건이다.
  뒤의 두 건은 overflow 수치 비교까지 도달하지 않았으므로 가로 넘침으로 단정하지 않는다.
  같은 트리에서 별도 화면 검사가 `dist`를 다시 빌드하고 있어 동시 실행 영향을 배제하지
  못한다. worker 1개 재검사와 별도 port/outDir 재검사는 완료하지 못하고 중지했다.
  첫 실행의 실패를 재현 확인된 제품 결함이나 통과로 바꾸지 않는다.
- 대비 게이트: 9건 통과
- backend 전체 suite: `2 failed, 1464 passed, 5 skipped, 8 warnings` (17분 29초).
  실패는 findings에 이미 기록된 screening orchestrator의 부분 성공 관련 2건이다.
  실행 중 다른 세션이 같은 저장소를 변경했으므로 새 HEAD의 검증으로 재사용하지 않는다.

사전 점검 시점에는 실제 C-1 판정, 첨부 다운로드, 개요·심층 모델 실행과 사람 추적 결정이
미완료였다. 후속 실제 첨부 실행 결과는 위 현재 범위 기록에 별도로 남긴다.
