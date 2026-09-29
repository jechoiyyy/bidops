# 1489번 실제 Luna 가정 분석 — 구현·검증 계획

작성: 2026-09-23. [목적](intent.md) · [명세](spec.md).
상태: 구현·관련 격리 검증 완료. 운영 적용 준비 완료, migration 직전 확인 대기. 운영 변경·모델 호출은 아직 승인/수행하지 않았다.

## 순서

- [x] 사용자 계획을 intent/spec/plan으로 기록한다.
- [x] 현행 입력·차단 검증·Codex 실행기·공용 슬롯·A안 시안의 재사용 경계를 확인한다.
- [x] Decimal 계산과 입력/가정/설정 불변 버전, migration·권한·승인·중복 방지를 구현한다.
- [x] 세 요청·상한 분할·단계 저장·실패/미연결 경고·부분 결과·REST를 연결한다.
- [x] 실제 결과를 받는 A안 보고서와 사전규격 상세의 요청/이력 UI를 연결한다.
- [x] 아래 관련 격리 검사를 수행하고 실패 원인을 구분해 영향 범위만 수정·재검사한다.
- [x] 적용 이미지·백업·롤백·migration head·서비스/설정 차이를 구체적으로 준비한다.
- [ ] 각 직전 확인 후 운영 migration·재배포·필요 설정을 적용한다.
- [ ] 1489 실제 입력 버전·이전 대비 변경·가정·전송 내용을 제시하고 호출 승인을 받는다.
- [ ] 실제 세 단계·보고서·운영 UI를 확인하고 인수 부족 항목을 수정한다.
- [ ] 운영 URL·입력/가정/설정·호출 수/시간·UI 결과·남은 경고를 전달한다.

## 한 번에 확인할 검증 묶음

| 요구사항 | 입력과 기대 결과 | 검사/증거 |
|---|---|---|
| 계산 | 12조합·월 300만원·VAT·반올림·6/12개월 민감도 | Decimal 단위 검사·API/UI 동일 표 |
| 승인/불변성 | 정상·변경 입력·다른 공고·재사용 승인·중복 제출 | 서비스/API·동시 요청 PostgreSQL 검사 |
| 단계와 저장 | 가짜 실행기 정상 3단계·2단계 실패·잘림·미연결 근거 | DB→REST 부분 결과·원응답 보존 |
| 공용 슬롯 | 기존 작업 실행 중·가정 분석 대기·lease 상실 | 합성 worker 관련 검사, 자동 재호출 없음 |
| migration | 빈 DB/이전 head 승격·제약·권한·불변 행 | 일회용 PostgreSQL 17.11, runtime head 일치 |
| A안 | 8절·12행·근거/미연결·집중/확대/초점/내려받기 | production build·두 viewport 의미/구조 검사 |
| 실제 인수 | 승인한 1489 입력→Luna→운영 보고서 | 실제 호출 ID/시간·운영 URL·두 폭 화면 확인 |

백엔드는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`와 일회용 DB의
`BIDOPS_TEST_POSTGRES_URL`을 명시한다. 실행 명령·통과/실패/skip·증거 위치는 실행 뒤
이 계획에 짧게 기록한다. 제품 경로를 실행하지 않은 가짜/단위 검사로 실제 연결을
검증했다고 쓰지 않는다. 문서 단계는 diff와 내용만 확인하며 앱 검사는 구현 뒤 수행한다.

## 수정과 운영 경계

입력 구성·출력 형식·모델 내용·검증 차단·저장/화면 오류를 구분한다. 저장 원응답으로
재처리 가능한 문제는 외부 호출 없이 검증한다. 프롬프트·입력·effort 변경의 실제 평가는
새 미리보기/승인/실행으로 수행한다. 수정 뒤 관련 경로만 재검증한다.

운영 DB SQL 수정 금지, 기존 입력/정책/보고서 덮어쓰기 금지, 무승인 전송 금지.
운영 변경 직전 확인의 근거는 저장소 [AGENTS.md](../../AGENTS.md)의
“운영 변경은 직전에 사람 확인을 받는다” 및 사용자 제공 계획 §5다.
승인 요청 전에 구현·격리 검사·적용/롤백 자료를 준비한다. 승인 대기나 외부 장애는
미완료로 표시하고 현재 결과와 다음에 필요한 조치를 명시한다.


## 실행 근거 (2026-09-23)

- 문서 세 개 작성·diff 확인 후 제품 변경에 착수했다. 기존 미커밋 Luna v2/v3와 A안
  시안 변경은 보존했다. commit/push 없음.
- 관련 pytest는 호스트 `web/backend/.venv/bin/python -m pytest`로 실행했고,
  PostgreSQL 변형은 일회용 `postgres:17.11` (`bidops-assumption-test-pg`)의
  `BIDOPS_TEST_POSTGRES_URL` 및 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`를 지정했다.
- 계산/스냅샷 2 passed. 입력 중복·상한 분할·잘림 차단·경고/본문 보존 4 passed.
- 새 서비스/REST: 정상 3호출, 2단계 실패·원응답 보존, 변경 입력, 활성 중복,
  PostgreSQL 동시 replay, immutable UPDATE/DELETE, 늦은 응답 차단 등 8 passed.
  승인 이후 코드 변경 시 전송 전 거부 1 passed 추가.
- 공용 슬롯 관련 6 passed. Codex runner/adapter 관련 기존·신규 검사 통과.
  기존 Luna API/worker 회귀와 새 runner 계약 검사 묶음 24 passed, skip 0.
- migration head·runtime 기동 게이트·Alembic ORM drift·실제 app/worker 권한은
  일회용 PostgreSQL에서 통과했다. 모듈 경계 묶음은 36 passed/1 failed였고,
  실패는 소유표에 신규 3표와 기존 0032의 Luna 2표가 빠진 것이었다.
  소유표·설계 문서를 맞춘 뒤 그 검사만 재실행해 1 passed.
- `npm run build` (TypeScript + production) 통과. chunk-size 권고 경고는 남아 있다.
- `PW_PORT=4187 npx playwright test --project=app tests/assumption-analysis.spec.ts`:
  4 passed. 1280×800·1440×900의 8절·12행, 실제 fixture 출처/미연결, 확대/집중,
  목차 위치·초점 복귀·동일 본문 내려받기, 실패 부분 결과, 1489 상세 승인과
  같은 프레임 이중 제출을 확인했다. 이 fixture는 테스트 DB/REST에서 생성한 합성 결과다.
  실제 Luna 품질/실제 운영 UI 검증이 아니다. 캡처는 `web/frontend/test-results/`.
- 운영은 read-only로 health/현재 bundle/프로필/과거 승인 입력을 확인했다.
  문서 묶음 `ff11113b-0b29-469f-b334-6be7575bb701` v2,
  프로필 `d970500a-e30c-46cf-85e0-7e9a9e854f2b`이며 실제 원문은 문서에 복사하지 않았다.
  중복 제거 뒤 문서 본문 44,825자, 회사 출처/구조화 항목 21,181자다.
  새 압축 입력의 선행 결과 없는 크기는 사업 79,267자, 회사 112,355자다.
  이는 전송 전 크기 확인이며 실제 세 요청 성공/속도/품질 근거가 아니다.

## 운영 적용 준비와 직전 확인

명령 묶음은 `/tmp/bidops-assumption-apply/compose.sh`에 저장했다. 기존 Luna 적용과 같은
6개 Compose 파일·5개 env 파일·prespec/luna profile이며 config 검사가 통과했다.
기존 활성 프로필/정책과 자동 시작 false 설정을 바꾸지 않는다. 가정 분석은 자체
동결 실행 계약을 사용하므로 기존 Luna v3 정책을 새 정책으로 교체하지 않는다.

- 목표 head: `0032_luna_deep_review` → `0033_assumption_analysis`.
- 이미지: web, migrate, analysis-worker, prespec-attachment-worker, codex-runner.
  첨부 worker도 runtime head를 읽으므로 새 이미지로 교체해야 한다.
- 현재 이미지 ID: `/tmp/bidops-assumption-apply/rollback-images.txt`.
  미커밋 diff 보존: 같은 폴더의 `worktree-before-deploy.patch`.
- DB backup: `backups/postgres/full/bidops-20260923T105309Z.dump`, 43,593,205 bytes,
  SHA-256과 pg_restore --list exit 0을 `backup-manifest.json`에 기록했다.
- 객체 백업: 같은 폴더 `object-backup-path.txt`에 경로, `backup-objects.exit`에 종료 코드.
  별도 ops 이미지 pull은 registry 권한 오류로 실패했다. 설치된 MinIO 서버 이미지에
  동일 고정 mc release가 있음을 확인하고 그 이미지에서 기존 version별 백업을 실행한다.
  awk 부재는 해시 첫 필드를 읽는 bash read로만 치환했으며 저장소 백업 스크립트는 유지한다.

실행은 다음 순서로 각 직전 확인을 받는다. 아래 명령은 **아직 실행하지 않았다**.

1. 활성 작업·cron 유입과 백업 완료를 다시 확인한다. 서비스 중지와 migration 승인 후:
   `compose.sh stop web analysis-worker prespec-attachment-worker`, `compose.sh run --rm migrate`.
   모델/운영 DB 행을 SQL로 변경하지 않는다. 빈 DB 테스트와 운영 migration은 별개다.
2. migration 성공/head/권한 확인 후 **별도 재배포 승인**:
   `compose.sh up -d --no-deps --no-build --force-recreate web analysis-worker prespec-attachment-worker codex-runner`.
   health와 기존 심층검토 이력 보존을 확인한다. 새 전송은 아직 하지 않는다.
3. 운영 `/pre-specs/1489`에서 가정 분석 입력 미리보기를 만들고 이전 대비 변경·hash·
   모델/effort를 제시한 뒤 **실제 전송 승인**을 받는다. 실제 실행 URL은 생성된 UUID로
   `/assumption-analyses/{id}`다. 승인 전 실제 결과 URL은 없다.
4. 실제 결과와 두 폭 UI를 확인한다. 부족하면 원응답/입력/프롬프트/화면 원인을 나누고
   필요한 변경·검사만 수행한다. 새 실제 호출은 다시 직전 확인을 받는다.

롤백은 백업된 이미지 ID로 서비스 tag를 되돌리는 것만으로 끝나지 않는다. 구 이미지의
runtime head는 0032이므로 운영 DB 0033과 일치하지 않는다. **새 가정 분석 승인 행이
없는 경우에만** 별도 확인 후 0033 downgrade와 기존 이미지 재배포를 함께 할 수 있다.
승인 행이 존재하면 downgrade는 거부하며 이력을 보존한 수정 이미지로 전진 복구한다.
DB/객체 전체 복원으로 다른 사람의 이후 작업을 잃는 조치는 별도 승인 없이는 하지 않는다.


### 준비 종료 확인

- 객체 백업 종료 코드 0, 1,368개 immutable version을 복사하면서 source/backup SHA-256을
  대조했다. 객체 manifest hash·경로는 `/tmp/bidops-assumption-apply/backup-manifest.json`.
- 최종 web/migrate/analysis-worker/prespec-attachment-worker와 runner 이미지 빌드 완료.
  운영 컨테이너는 교체하지 않았다. 이미지 내부 head와 입력 구성 코드 hash를 host와 대조했다.
- 로컬 롤백 태그 `before-assumption-analysis-20260923`를 HEAD에 만들었다.
  태그에 없는 미커밋/새 소스는 같은 준비 폴더의 `source-checkout.tar.gz`와 diff로 보존했다.
- read-only 조회 시 공용 work_job의 queued/running은 0, 운영 head는 0032였다.
  실제 변경 직전에 다시 확인한다. 실제 Luna 호출 수는 이번 작업에서 **0회**다.
- 다음 미완료 항목: migration 승인/실행 → 재배포 승인/실행 → 실제 입력 미리보기·
  전송 승인 → Luna 실제 결과·운영 두 폭 UI 인수. 운영 보고서 URL은 아직 없다.
