# RL-04 제안서 초안 격리 스택 확인 — bidops-local `bidops_rla_t11`

2026-10-18 KST, run `rlb-20261017`, 기능 `RL-04-proposal-draft` STEP-009.

이 문서는 **T10 mock 전 경로**(모델 호출 0, `mock_reference`)와 **T11 실제 초안 1건**(아래 절: 모델 호출 6, partial — 6절 중 4절 completed, track_record·operations_sla `proposal_section_invalid`, `unmeasured_reference`)의 기록이다. 어느 결과도 품질 근거·운영 완료 근거가 아니며 T10은 T11을 대신하지 않는다. `real_data_run` 증명은 사람 확인 대기(B57).

## T10 mock 전 경로

### 환경

**이미지와 worktree**
- 이미지 `bidops-local:rlb-20261017-rl04` = `sha256:b350db1e69edf0bda023dc158710be0b3785fb8b19dc6a7d4c8088b9139fc3f7`. RL-04 worktree(배치 HEAD 9ae53ec + RL-04 STEP-001~008 미커밋)에서 linux/amd64로 빌드했다.
- 이미지 안에서 확인한 것:
  - `import reportlab` 성공, 5.0.1(`renderer_version=reportlab==5.0.1`).
  - `/usr/share/fonts/truetype/nanum/NanumGothic.ttf`(sha256 `48a28e97…e733`)와 `NanumGothicBold.ttf`(`454eb3f5…3bc9`)가 있다.
  - 정책 파일 sha256이 worktree와 같다: `proposal-policy-luna-v1.json` `0eb36cf9e4318e447dd2c66f59a060a9ec1d87b92c23326200867060973e7d91`, `analysis-policy-luna-rl-v6.json` `84e94954…534a`.
  - `runtime-privileges.sql` `7337209e…1765`. migration head는 `0041_proposal_draft`.

**DB**
- `bidops_rla_t11`(bidops-local 안 T11 전용 DB). 적용 전 `pg_dump` sha256은 `f4c39d82…768d`.
- `rla-migrate`(새 이미지)를 exit 0으로 마쳤다: `0040_card_analysis → 0041_proposal_draft`. 같은 실행에서 runtime privileges를 적용했다. `proposal_draft`·`proposal_section`·`proposal_sentence_edit`·`proposal_export` 네 표가 생겼다.
- 실제 경로 DB `bidops_rla`는 건드리지 않았다.

**MinIO** (bidops-local, 추가형 변경, 승인됨)
- RL-04 `scripts/minio-init.sh`에서 proposal-pdf 부분의 명령만 같은 순서로 실행했다: `mc mb`, `version enable`, `admin user add`, `policy create/attach`, `ilm add --expire-days 365`.
  - 그 결과 버킷 `bidops-proposal-pdf`(versioning `Enabled`), 사용자 1명, 정책 `bidops-proposal-pdf`(그 버킷 Get/Put/List만), ILM 만료 365일이 생겼다.
- 기존 버킷 4개·사용자 5명·`bidops-model-response` ILM(90일)은 바뀌지 않았다. 사용자는 5명에서 6명이 됐다.
- 새 키는 Git 밖 `env/rl04-proposal-pdf.env`(0600)에 생성했고, 값은 어디에도 출력하지 않았다.

**서비스**
- `rla-web`과 `rla-analysis-worker`를 rl04 이미지와 다음 설정으로 띄웠다:
  - `BIDOPS_ANALYSIS_PROVIDER=mock`, `BIDOPS_REFERENCE_WORKFLOW_MODE=true`, `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`
  - RL 선택 행은 v6 `f3247812-…`, `BIDOPS_PROPOSAL_POLICY_VERSION_ID`는 아래 정책 행.
  - 폰트 디렉터리는 기본값이다(env 없음).
  - proposal-pdf 키는 web에만 있다. worker에는 키가 없다.
- `rla-codex-runner`는 계속 멈춰 있다.

**정책·승인** (CLI만, actor jechoi)
- `import-profile-policy --label proposal-policy-luna-v1 --expected-policy-sha256 0eb36cf9…7d91` exit 0. 정책 행은 `dbf69fce-0d75-407c-a2be-0ff042978eaa`.
- `approve-transfer-policy --policy proposal-policy-luna-v1 --daily-cap 1`: dry-run exit 0, 이어서 실제 exit 0. 승인 `2dae67f0-e4df-4d8c-b98e-a8b4d9791c7a`(scope proposal, request `fc5baa14-dc36-4934-9127-f2a1e8177ccf`).
- RL v6 승인 `3f8b5ad2-…`(T11 mock 8차)는 그대로 활성이다.

**대상**
- 사업기회 14(폴리텍 사전규격 notice 14).
- 판정은 RL-03 T11 8차 v6 mock 판정 attempt `d57258e8-2643-4531-ae76-610c159c692f`(completed, "판단 불가", 카드 unit 27개).

### 결과

| 단계 | 결과 |
|---|---|
| 초안 요청 `POST /api/opportunities/14/proposal-requests` (actor jechoi) | 202 `draft_id=38fc8ce5-d16c-475f-a24a-74f1d52d4e68`, `queued`. 감사 `proposal.draft.created`: `provider=mock-analysis`, `quality_status=mock_reference`, `section_count=6`, `verdict_attempt_id=d57258e8-…`, `approval_id=2dae67f0-…` |
| worker | proposal_section WorkJob 6개 모두 `completed`. 절 6개는 각각 revision 1, `completed`이며 input·result sha가 절마다 다르다. 감사는 `proposal.section.claimed` 6건, `proposal.section.completed` 6건(`call_count=1`, `repair_count=0`, `quality_status=mock_reference`). 초안은 `status=completed`, `stage=draft`이고 약 5.6초 걸렸다 |
| 보기 `GET /api/opportunities/14/proposal` | 아래 별도 표 참고 |
| 문장 수정 | `POST …/sentences/ee1f1a4f-c06f-5410-86b1-285ee9cddea8/edits` 201 `edit_id=bf13d8b2-d421-420f-8b5f-a1b0f0e4ea72`. 보기에서 그 문장이 `edited=true`이고 새 문장이 반영됐다 |
| 검토 | 절 6개 `PATCH …/sections/{key}/review`가 모두 200이다. 절은 전부 `reviewed`, 초안 `stage=reviewed`, `reviewed_sections=6` |
| 제출 준비 | `PATCH /api/proposals/{draft}/stage {stage:"ready"}` 200 → `stage=ready` |
| 내보내기 2회(같은 overlay) | 1회차 201 `{export_id:1e874282-7a79-46e0-a1c8-7b37d71b5508, pdf_sha256:9fe9240a61b4f89301f4c99e74dc399ae775c9229b4244fc3bb2a555178425ee, created:true}`. 2회차는 같은 export_id와 sha에 `created:false` |
| PDF 받기 `GET …/exports/1e874282….pdf` | 200 `application/pdf`, 123,100 B. 헤더 `X-BidOps-Export-Sha256`이 내려받은 파일의 sha256(`9fe9240a…25ee`)과 같다. 내용은 아래 별도 표 참고 |
| 객체 저장 | `content_object` `5f039eff-ffa9-477f-92f7-26d38947be7f`(sha 같음, `retention_class=proposal-pdf-365d`, 암호화 없음). location은 namespace `proposal-pdf`, version `07175134-00f2-465b-b86c-d411cad2033a`, `verified`. MinIO `bidops-proposal-pdf`에 같은 version id, 120 KiB 객체가 1개 있다 |
| 다시 수정 → 새 내보내기 | 수정 `edit_id=53a96635-b171-4d7b-972f-472eb8f02438` → 201 `{export_id:678a062e-72a0-4bc0-bfe8-c9cb10293036, pdf_sha256:21d298851cad26e02f8113195b8872a518d3a15111669bc981cea2520f1f967d, created:true}`. sha가 다르고 overlay sha도 다르다(`6ce7eca3…` → `9f465439…`). 받은 PDF sha256도 헤더와 같고 16쪽이다. `latest_export`는 새 export를 가리킨다 |
| 전송·상한·품질 | `analysis.transfer.sent` 0건. `proposal_cap_usage`는 (보낸 단위 0, 예약 0), RL `today_used=0`. 생성·완료 감사의 `quality_status`는 `mock_reference`이고 PDF 표지에도 "모의 참조 결과(mock_reference) · 실제 모델 결과 아님"이 찍힌다 |
| 활동 `GET /api/opportunities/14/activity` | 첫 항목 `draft_prepared` "제안서 초안 준비", 링크 `/opportunities/14/proposal?draft_id=38fc8ce5-…` |
| 화면 `/opportunities/14/proposal` 1440x900 | `proposal-tab-1440.png`에서 확인했다: 제안서 탭, 단계 목차·초안·검토 완료·제출 준비, 절 탭 6개, 요구사항 연결 27/27, 채워야 할 것 12건, 최근 PDF 링크. API는 200이고 가로 넘침이 없다. 금지 문자열(`policy`·`sha256`·`gpt-6-luna`·`unmeasured_reference`)은 DOM에 없다. 1280 폭은 찍지 않았다 |

보기 `GET /api/opportunities/14/proposal`의 세부:

| 항목 | 결과 |
|---|---|
| 절 | 6개 |
| 요구사항 덮음 | `requirement_coverage={total:27, linked:27, unlinked_unit_ids:[]}` |
| 문장 수 | statement 143, placeholder 12, proposed_figure 0 |
| 출처 | 출처 없는 statement 0. 출처 종류는 requirement_unit 60, company_fact 82, notice_meta 1 |
| 금지 내용 | 통화 금액·투입 인원·기간 약속 패턴이 출처 인용 숫자 없이 나온 문장 0 |
| 빈 자리 표시 | 가격 2, 실적증명서 발급 건 목록, 투입 인력 수, 전략 수치, 성능 목표 수치, `project:certified_list`·`current_list`·`web_cms_list` 확인, `staff:pm`·`grade_distribution`·`dispatch_partner` 확인 |
| 절별 (statement/placeholder/연결) | overview 4/1/3, track_record 77/4/0, strategy 27/1/27, requirements 27/1/27, operations_sla 3/1/3, organization 5/4/0 |

PDF 내용(`pdfinfo`/`pdffonts`):

| 항목 | 결과 |
|---|---|
| 형식 | ReportLab, A4, 16쪽 |
| 폰트 | NanumGothic·NanumGothicBold 부분 임베드 |
| 1쪽 | `pdf-page1.png`에서 확인했다: 한글 정상, 표지 "2027년 홈페이지 유지관리 용역 / 조달청 인천지방조달청 / 초안 · 2026-10-18 · 제출본 아님 / 모의 참조 결과(mock_reference) · 실제 모델 결과 아님" |

### 한계

- mock 출력이다. 문장은 결정적 mock client가 만들었고 입력 계약·검증·저장·PDF·화면 연결만 증명한다. 모델이 쓸 문장 품질, 금지 내용 회피, 덮음 완성도는 증명하지 않는다.
- 판정 입력도 mock이다(T11 8차, 모든 대조 `unknown`, "판단 불가").
- 화면은 1440 한 장만 찍었다.
- 재생성(`regenerations`), `partial`, 실패 절의 "생성 실패" 페이지, 마감 표시는 이 실행에서 돌리지 않았다(단위·PG 테스트 범위).

## T11 실제 초안 1건

상태: **pending.** RL-03 T12가 통과한 실제 판정이 아직 없다. B37에 따라 배치 B는 실제 호출을 끝냈고, `bidops_rla`에는 활성 승인이 없으며 최신 실제 판정은 `needs_human_review`다. spec 조건("RL-03 T12가 통과한 판정으로 초안 1건")이 충족되기 전에는 실행하지 않는다.

## 재현

overlay·명령·로그는 Git 밖 `.sdlc/local-runtime/rlb-20261017/`에 있다.
- `compose-t11-rl04.sh`, `rla-rl04.yml`, `t11-rl04.env`, `minio-proposal-pdf.sh`
- `logs/t10-*`, `logs/minio-*`, `t10-artifacts/`(PDF 2개·헤더)

## T11 실제 초안 1건 (2026-10-18 08:01Z UTC = 17:01 KST, 사용자 승인 B51·B55) — **partial(4/6 절 completed)**

- 판정 입력: RL-03 실제 판정 `667bf04d-e83c-4be1-93fe-61549c43ad69`("판단 불가", matrix 32행 모두 unknown — 회사 근거 상태 D13). bidops_rla, 이미지 `rlb-20261017-b55`, runner `aaaf896f…`(proposal-section-v1 포함).
- 제안서 정책 행 `e08e4b21-47af-495f-9c21-87ace58982f0`(sha `0eb36cf9…`), 승인 `4b6dad7d-a60e-4f3b-90b9-9e7d02dd7af2`(purposes proposal, cap 1). request `daedbce8-dfba-4c09-a86c-5b6ae72baa86`, draft `5d627b0f-4fa6-48e9-80ab-b9cc10cd0c2f`.
- 호출 6회(절당 1, repair 0, 상한 12 안), `analysis.transfer.sent` 6건, runner 실패 0, 08:05Z settled `partial`(stage `draft`).
- 절 결과: overview completed(문장 6), strategy completed(7, placeholder 1), requirements completed(28, placeholder 1, 카드 27개 연결), organization completed(9, placeholder 4 — 인력 수치는 빈 자리), **track_record·operations_sla failed `proposal_section_invalid`**(사람 검토, 재시도·절 다시 쓰기 없음 — 승인 조건). 문장 확인 6·placeholder 6·제안 수치 0.
- PDF: export `4e278aae-7d31-4f52-a8ea-b81956903131`, `pdf_sha256 be6e412b…4058` = 헤더 = 파일 sha, 실패 절은 "생성 실패" 표시. 품질 표식 `unmeasured_reference` — 품질 근거 아님.
- 실패 절 오프라인 진단(재생 해시 일치, 외부 호출 없음): 두 절 모두 **식별자 하나를 잘못 옮겨 적은 실제 모델 오류**. operations_sla는 unit id `…005a1e:12:SER-1`의 hex 한 글자를 바꿔 씀(인용은 올바른 SER-1 원문, unit 참조 49개 중 1개), track_record는 `project:2025-16`의 `project:` 접두를 빠뜨림(인용 일치, 회사 사실 참조 176개 중 1개). 증거 계열이라 repair 없음이 맞고, 참조만 고치면 두 절 모두 통과. 원인 구조: 긴 불투명 식별자를 절마다 수십~백여 번 복사하게 하는 계약 — 백로그(입력 안 짧은 별칭 U1·F1을 코드가 정확 조회로 되돌리는 계약 v2).
