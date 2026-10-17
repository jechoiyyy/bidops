# RL-03 카드 판정 실제 스택 확인 — bidops-local (격리)

2026-10-17, run `rlb-20261017`, 기능 `RL-03-fit-verdict`. 가짜 서버·단위 테스트로 증명되지 않는 경로(REST↔DB↔worker↔화면, 자동 트리거, 실제 Luna 호출)를 격리 스택에서 확인하는 기록이다. **T11 mock 경로는 8차까지 실행했고(최종 v6 completed), T12 실제 Luna 판정은 1~7차 모두 판정을 얻지 못해 pending이다(결정 B37, [findings](../../../tracking/findings.md) "RL-03 카드 판정은 제약 하나의…").** 실제 전송 합계: attempt 7건 중 HTTP 호출에 이른 6건(2차~7차), 모델 호출 합계 8회(2차 1·3차 2·4차 1·5차 1·6차 2·7차 1 — 1차는 호출 전 실패), 모두 사용자 승인 범위(인터뷰 D10, B26·B29·B32·B33·B35) 안. 결과는 `unmeasured_reference`(mock 경로는 `mock_reference`)로만 적고 품질·운영 완료 근거로 쓰지 않는다.

- 환경: 격리 스택 `bidops-local`(운영 `bidops` 스택·운영 DB·cron·origin push 금지). 이미지 `bidops-local:rlb-20261017-rl03`(최종 `4071cb95…`)·`bidops-local:rlb-20261017-runner`(`78fe765f…`), DB `bidops_rla`(실제 경로)·`bidops_rla_t11`(mock), web `127.0.0.1:18797`, migration head `0040_card_analysis`. 최종 상태: `bidops_rla` 활성 전송 승인 없음, runner·analysis worker 정지.
- 범위·한도(배치 B 인터뷰 [D1~D13](../../../work/groups/RL/batch-b-interview.md)): 사전규격만, 개요 비의존, 전송은 `confirmed` 사실 전부 + `proposed`/`unknown` 키·상태만, 인증은 호스트 개인 로그인 `auth.json`을 runner에만 읽기 전용 마운트(값·내용 미기록), runner만 `luna-egress`, 정책 승인·요청 actor `jechoi`.

## T11 mock 경로

상태: **실행함(8차 기준 completed — v6 정책, unit 32·batch 4·호출 8, extract 제약 22개(batch별 1·5·2·14) 인용 전부 블록 안 유일, `missing_sections=["contract"]`, 판정 "판단 불가", `today_used=0`, 전송 감사 0).** 이하 7차까지의 요약: 3차에서 브리핑 추천 → 자동 트리거 → v1 mock 실행이 이어졌고 결과는 `needs_human_review`였다. 4차에서는 v2 정책(`card-sections-v2`)으로 수동 요청해 `completed`가 나왔다: 판정 "판단 불가", `missing_sections=["contract"]`, 활동 `verdict_completed`, 브리핑 판정 표시, `today_used=0`, 전송 감사 0. 1~3차 기록은 아래에 그대로 둔다. 결과는 `mock_reference`이며 품질 근거가 아니다.

### 준비한 것 (2026-10-17, 격리 스택 `bidops-local`, DB `bidops_rla`)

| 항목 | 결과 |
|---|---|
| 이미지 | `bidops-local:rlb-20261017-rl03`(web/Dockerfile, linux/amd64) `sha256:405877744150c1a8a75d9f3cbb1fc7bfce8b5622f3243bb4611f42a0933d4f6a`; `bidops-local:rlb-20261017-runner`(web/codex-runner/Dockerfile, amd64, `codex-cli 0.162.1`, card schema 3개 sha가 worktree contracts와 일치) `sha256:afa08a41c5eee0736edd53e0c6fee029652c73c9967eb07d4eecd34d142bd52f`. 이미지 안 정책 파일·`runtime-privileges.sql` sha256 = worktree(`9687c49b…6c4a`, `269d6a03…8383`) |
| 백업·migration | 적용 전 `pg_dump -Fc` `before-0040-bidops_rla.dump` sha256 `18903926c6a2fb555ea553815614fc1d6fcb408ca6a1c54a8f87f4f05aa26220`(TOC 1286행). `rla-migrate` exit 0: `0039_opportunity_note → 0040_card_analysis`, 새 표 4개 존재 |
| 서비스 | `rla-web`(새 이미지, `127.0.0.1:18797`, `/api/health` 200). `rla-document-worker`(기존 native arm64 문서 worker 이미지 `bidops-local:document-arm64-cac9b4f7-20261009` 재사용, `network_mode: none`, rla 전용 scratch 볼륨 `bidops-local_rla-document-scratch`) 기동 유지. `rla-analysis-worker`는 기동 확인 뒤 중지(작업 0건이라 claim 없음). `rla-codex-runner`는 정의만(profile `rl03-luna`, 미기동) |
| 정책 행 | `import-profile-policy --label analysis-policy-luna-rl-v1 --expected-policy-sha256 9687c49b…6c4a --actor jechoi` exit 0 → `policy_version_id=b5909aab-627f-495c-90d2-db3b377fde52`, `policy_sha256=9687c49be2cfb0400b97aaa038d19536e2b6a7b792ab957569ef9bc319976c4a`(행 canonical sha = 파일 sha). CLI가 함께 넣은 legacy profile 행 `31c42292-ef27-496c-8b7b-3967f8fd508f`(`company-profile.md` sha `11e68c31…721a`; RL 경로는 회사 knowledge profile을 쓴다). `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`로 선택 |
| 정책 승인 | `approve-transfer-policy --policy analysis-policy-luna-rl-v1 --actor jechoi --daily-cap 2` dry-run exit 0 → 실제 exit 0: `approval_id=4829f92a-55e2-4103-950f-cfef3aa62341`, `request_id=ed2aae03-579b-41a6-93b9-0af065a51479`, model `gpt-6-luna`/high, CLI 0.162.1. `GET /api/analysis/transfer-policy` → `active.approval_id`·`policy_sha256`·`daily_cap=2`·`approved_by=jechoi` 일치, `today_used=0` |
| 폴리텍 회차 | host `data/runs/hp03-polytech-prespec-20261012-20261015T131653Z`(파일 3개)를 수정 없이 `bidops-local_rla-pipeline-data`의 `runs/`로 복사, 파일별 sha256 host=volume 동일. `ingest.cli --run … --collection` exit 0: run `hp03-polytech-prespec-20261012-20261015T131653Z--20261015T131654.385361Z`, notices 60(pre_spec_sw 60/334), 경고 1건 `screening_results_missing`(판정 파일 없음, HP-03과 같음). 공고 `R26BD00283242` → notice **362**(pre_spec, `sw_business_status=Y`, included), 사업기회 **353**(공식 링크), 첨부 946(`g2b`, URL만, 바이트 없음) |
| 로컬 원본 | `~/orca/fixtures/RFP/(붙임2) 2027년 홈페이지 유지관리 용역사업 제안요청서(수정본).hwp` sha256 `8b6cbf1a7da6f242dae0a1a90b2513513178667a7fc2343e93cbcf6318005a1e` = 이전 수집본 `R26BD00283242-fileSeq2.hwp`. **아직 등록하지 않았다**(아래 막힌 것 2) |
| 게이트 확인(쓰기 0) | `GET /api/opportunities/353/verdict` 200 `availability=none`, `notice_id=362`. `POST /api/opportunities/353/verdict-requests`(actor jechoi) → 409 `bundle_not_ready`(정책 승인·cap·SW=Y를 지나 묶음에서 닫힘, 개요 조건 없음). `POST /api/notices/362/document-bundles`(개요 플래그 false) → 403 `effective_grade_ineligible`. 확인 뒤 `verdict_request`·`deep_review_preview`·`deep_review_attempt`·362 묶음·`prespec_overview_run` 모두 0행 |

### 막힌 것 (리더 결정 필요)

1차 기록이다. 1은 B16, 2는 B15·B18, 3은 B17·B19·B20으로 처리됐고 남은 차단은 아래 "2차"에 있다.

1. **card-v1 mock provider가 없다.** `BIDOPS_ANALYSIS_PROVIDER=mock`(기존 mock 경로)이면 `DeepReviewService._run_card_claim`이 첫 호출·`analysis.transfer.sent` 전에 503 `service_unavailable`("Luna 실행 비활성")로 닫는다(`web/backend/app/deep_review/services/deep_reviews.py`). `MockAnalysisClient`는 card 계약(`invoke_prompt(prompt, contract=card-*)`)을 처리하지 않고 codex-runner(`web/codex-runner/runner.py`)에도 가짜 모드가 없다. 카드 출력을 만드는 가짜는 테스트 안의 주입 client(`tests/app/test_card_analysis_postgres.py::FakeLuna`)뿐이다. 필요한 것은 둘 중 하나다: (a) 제품 쪽 card용 mock client + card 경로의 mock 허용 + `quality_status=mock_reference` 표식, (b) codex-runner wire(`POST /calls`→`GET /calls/{id}`→`DELETE`)를 따르고 `FakeLuna._valid`처럼 prompt 입력에서 유효 단계 출력을 만드는 테스트 전용 가짜 runner 이미지(`rla-luna-internal`에만 연결). 지시대로 새로 만들지 않았다.
2. **폴리텍 묶음을 `ready`로 만들 제품 경로가 없다(D8 전제와 충돌).** 적재가 만든 첨부 946은 `g2b` URL 행이라 바이트가 없으면 묶음 issue 계산이 blocking `attachment_bytes_missing`을 낸다. 로컬 파일은 묶음 업로드(`POST /api/document-bundles/{id}/documents`)로만 들어가는데 그 경로는 **새 manual 첨부**를 만들 뿐 946을 채우지 않고, 946은 제품 경로로 retire·삭제할 수 없다(나라장터 첨부 삭제 금지, retire는 회차 적재만). 또 개요 플래그 false에서는 `우선 검토` 등급이 없는 SW=Y 사전규격의 묶음 생성 자체가 403이다. 선택지: (i) 사용자 승인 아래 첨부 worker로 946 한 건만 G2B 취득하고 sha256이 위 로컬 원본과 같은지 확인(D8 변경), (ii) 기존 g2b 첨부에 로컬 원본을 sha 확인 뒤 연결하는 제품 경로 추가(코드 변경), (iii) 그 밖의 결정. 묶음 업로드를 먼저 해 두면 (i)에서 같은 원문이 두 첨부로 들어가 unit이 중복되므로 업로드도 하지 않았다.
3. **mock attempt도 실제 호출 상한을 소비한다.** `transfer_policy.today_used`는 RL 정책 행으로 만든 오늘(KST, `approved_at`) attempt 전부를 센다. T11 attempt를 T12와 같은 날 만들면 `--daily-cap 2`에서 T12는 재시도 없이 1회만 남는다(다음 KST 날이면 다시 2). 또 브리핑에 한 번 들어간 공고는 다시 추천되지 않고(`_notice_population`의 `itemized` 제외), T12가 completed면 같은 조합 자동 트리거는 `verdict_current`로 멈추므로, 자동 트리거를 폴리텍으로 증명하려면 T12보다 먼저 해야 한다(아니면 다른 공고).

### 2차 (결정 B15~B20 반영 뒤, 2026-10-17) — B15 CLI에서 다시 막힘

- 이미지 재빌드 `bidops-local:rlb-20261017-rl03` = `sha256:c86bc40ef4caaeb6107a357ccfb0d9045791814026ebddec60fe4e0157230ad8`(attach CLI 포함, 정책·권한 파일 sha 불변, 0040 파일 불변). runner 입력(runner.py·Dockerfile·schema 5개)은 1차 빌드 뒤 바뀌지 않아 runner 이미지는 그대로.
- T11 전용 DB `bidops_rla_t11` 생성(owner 소유, schema `bidops` 소유자 migrate, CONNECT app·worker·ro_backup — `bidops_rla`와 같은 ACL) → `rla-migrate` exit 0, head `0040_card_analysis`.
- 루트랩: `import-company-knowledge`(ontology.v2 sha `7e6f4d8a…96d7`, source.v2 sha `5ffdcef0…f952`) dry-run exit 0 → import exit 0: company `68bcd51c-c30a-4a9e-93be-7785f5248043`, graph `1f9066dd-81d9-499b-82a4-c218feace489`(sha `a638050f…28f0`), profile `5cfea85f-5a01-49e7-a0ed-53550403f4c8`, confirmed 126·proposed 1·unknown 21 → activate exit 0(revision 1).
- 정책 행 `27cb7a4a-ddac-4949-ace7-cddd7b344323`(sha `9687c49b…6c4a`) → 승인 dry-run·실제 exit 0: `approval_id=5f0754e1-5b45-49ce-a661-7b82c433a2f9`, cap 2, actor jechoi.
- 폴리텍 회차 적재 exit 0(60건, 경고 `screening_results_missing`): notice **14**(SW=Y), 사업기회 **14**, 첨부 **18**(`g2b`, 이름 `첨부 1`).
- `attach-local-original --notice-id 14 --attachment-id 18 --file "/fixtures/rfp/(붙임2) 2027년 홈페이지 유지관리 용역사업 제안요청서(수정본).hwp" --expected-sha256 8b6cbf1a7da6f242dae0a1a90b2513513178667a7fc2343e93cbcf6318005a1e --actor jechoi --dry-run` → **exit 2 `unsupported_extension`**. 원인(제품 결함): `prespec_attachments._local_original_target`가 `name = attachment.name or fallback_filename`으로 DB 이름을 먼저 쓰는데, G2B 첨부 행 이름은 자리표시자(`첨부 1`, 확장자 없음)라 `_safe_filename`이 실패한다. 이 회차 g2b 첨부 79건이 모두 `첨부 N` 형식이라 실제 G2B 행에는 항상 거부된다(테스트 fixture는 `제안요청서.hwp`처럼 확장자 있는 이름이라 못 잡음). dry-run이라 쓰기 0. 지시대로 코드는 고치지 않았다.
- 그래서 묶음 준비·브리핑(`--date 2026-10-16`)·자동 트리거·mock attempt·판정 보기·활동·브리핑 표시는 이번에도 실행하지 않았다. `bidops_rla_t11`은 위 상태(적재·승인까지)로 남아 있다. 자동 트리거는 켠 적 없다.

### 3차 (결정 B22 반영 뒤, 2026-10-17) — mock 전 경로 실행, 결과 `needs_human_review`(원문 절 부족)

- 이미지 재빌드 `bidops-local:rlb-20261017-rl03` = `sha256:ca06cc94b32b3bc4faff08523589dff3d831135e2cf2f6535cad1beb39250440`(B22 반영 확인, 0040·정책·권한 sha 불변). runner 이미지는 그대로.
- **첨부 연결**(`bidops_rla_t11`): `attach-local-original --notice-id 14 --attachment-id 18 --file "/fixtures/rfp/(붙임2) …(수정본).hwp" --expected-sha256 8b6cbf1a7da6f242dae0a1a90b2513513178667a7fc2343e93cbcf6318005a1e --actor jechoi` dry-run exit 0 → 실제 exit 0: `document_version_id=90e9e876-8d43-48d2-96a7-808e5ea81760`, scan `clean`, 1,224,192 B, 취득 상태 `대기→완료`. `rla-document-worker`가 HWP를 변환해 structure `944579cd-40bb-4f23-b1c1-db53d39276e1`(ready, block 1,603) → 문서 준비가 묶음 `c9c60422-f21b-4349-ab72-e76e7c93a5df`를 만들고 확정(`ready`, `auto-preparation`, 감사 trigger `operator_local_original`). 감사 `prespec_attachment.local_original` 1건(actor jechoi).
- **브리핑 후보 조정(격리 DB에서만, staging)**: 읽기 전용으로 추천 순위를 계산해 보니 폴리텍(notice 14)은 점수 50 동점의 11위였고 `top_n=10`이라 빠졌다(동점은 마감·최초 관측 시각까지 같아 notice id로 갈림). 그래서 **10위 공고 11(산림기술정보통합관리시스템 유지관리)을 제품 REST `POST /api/pre-specs/review-exclusions`(actor jechoi, 사유 기록)로 검토 제외**했다. 감사 `pre_spec.review_exclusion_changed` 1건. 이 조정은 `bidops_rla_t11`에만 있고 `bidops_rla`에는 없다.
- **실행 설정**: rla-web·rla-analysis-worker를 `bidops_rla_t11`에 연결하고 `BIDOPS_ANALYSIS_PROVIDER=mock`, 참조 모드 true, `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=true`(이 단계에서만), 정책 행 `27cb7a4a-ddac-4949-ace7-cddd7b344323`.
- **브리핑**: `python -m app.lifecycle.cli build-briefing --date 2026-10-16 --json` exit 0 → `status=collection_incomplete`(이 DB에 수집 회차 없음, 경고 `collection_run_missing`), 추천 10건, 폴리텍 항목 `ed381865-6c20-4d61-b37c-8ced78acb3b7`(10위). 다른 추천 9건은 문서가 없어(취득 `대기`) 아무 것도 시작하지 않았다.
- **자동 트리거 → mock 실행**: 브리핑 hook이 attempt `dc5072af-a457-4fbd-842b-047fb5415973`(review `99cb3adb-628b-463b-a0d5-f3100eb4d342`, sequence 1, `requested_by_name=system:transfer-policy`)를 만들고, 감사 `deep_review.auto_create`·`deep_review.external_transfer_approved`(actor_kind `system`, `system:transfer-policy`)가 남았다. worker가 claim → mock card client로 `card_analysis_stage` 13행(extract·compare 0~4, role 3개; 약 0.8초) → 종합 전에 **`card_source_selection_incomplete`로 failed**(WorkJob `failed`, attempt_count 1). WorkJob 1건, `verdict_request` 0건, 개요 run 0건.
- **판정 보기** `GET /api/opportunities/14/verdict`: `bidops.practitioner-verdict-view.v1`, `availability=needs_human_review`, `error_code=card_source_selection_incomplete`, `missing_sections=["budget","eligibility","evaluation","contract"]`, `is_current=true`, `stale_reasons=[]`, `notice_id=14`, `opportunity_id=14`, `briefing_item_id=ed381865-…`, `quality_status=mock_reference`, `result=null`, `partial_matrix` 33행(전부 `unknown`), `partial_stage_ids` 13, `source_binding.company_sha256`=graph sha `a638050f…28f0`.
- **활동** `GET /api/opportunities/14/activity`: `pre_spec_opened`만 있고 `verdict_completed` 없음 — spec대로 failed는 활동 사건이 아니다. **브리핑** `GET /api/briefings/2026-10-16`: `bidops.briefing.v2`, 폴리텍 `verdict_display="분석 대기"`(completed가 없으므로).
- **상한·전송**: `today_used=0`(승인 `5f0754e1-5b45-49ce-a661-7b82c433a2f9`, cap 2), `analysis.transfer.sent` 0건, raw response 감사 0건. 모델·runner·나라장터 호출 0.
- **증명된 것**: 브리핑 추천 → hook(이미 ready인 묶음) → 정책 승인 → worker 역할 실행 → mock 단계 저장 → 판정 보기 `needs_human_review`·부분표 → 상한 미소비·전송 감사 없음.
  **증명 못 한 것**: completed 경로(종합 단계, 활동 `verdict_completed`, 브리핑 판정 글자, Slack 스레드 건너뜀), 준비 시작→ready hook 경로(묶음이 브리핑보다 먼저 ready였다), cap 큐·drain, 화면.
- **원인(데이터·선택 규칙, mock 문제 아님)**: 카드 원문 선택 규칙(`card-sections-v1`)은 번호 붙은 제목(`1.`, `Ⅰ.`)만 절 제목으로 본다. 폴리텍 RFP는 `1. 사업개요`·`4. 추진일정`은 번호 제목이지만 예산·입찰참가 자격·제안서 평가 방법은 사설 영역 글머리표 U+F06D(Wingdings ■)로 시작하는 문단(`paragraph-1-76`·`-252`·`-265`)이라 제목으로 잡히지 않는다. 계약 키워드(`계약조건`·`대금지급` 등)도 제목으로 나오지 않는다. **같은 원본·같은 규칙이므로 T12 실제 실행도 extract 5회 + role 3회(실제 호출 8회, 상한 1 소비) 뒤 같은 code로 끝난다.**
- 뒤처리: T11 worker 중지, `t11.env`의 자동 트리거를 false로 되돌림, rla-web을 `bidops_rla`(provider vllm, 자동 트리거 false)로 되돌림. `bidops_rla_t11`은 위 상태로 남아 있다(공고 11 검토 제외 포함).

### 4차 (결정 B23·B24 반영 뒤, 2026-10-17) — v2 정책으로 completed

- 이미지 재빌드 `bidops-local:rlb-20261017-rl03` = `sha256:f81edf9247f49e9ead37fb508292393cec33fee2b2a700b77c7e7ca907bf8036`. 이미지 안 `analysis-policy-luna-rl-v2.json` sha256 `e733e94a02b1240794ac50b7397d3974fb241917cf73fdeed009ba4ba0c4ff3b`. 0040·권한 파일은 그대로. runner 입력(runner.py와 schema 5개)이 바뀌지 않아 runner 이미지는 다시 빌드하지 않았다.
- **v2 정책 행과 재승인**(두 DB, actor jechoi, `--daily-cap 2`). 순서: `import-profile-policy --label analysis-policy-luna-rl-v2 --expected-policy-sha256 e733e94a…ff3b` → 선택 env를 v2 행으로 변경 → v1 승인 철회(`revoke-transfer-policy`, 사유 기록) → v2 승인 dry-run → 실제 승인. 모두 exit 0.

  | DB | v2 행 | 철회한 v1 승인 | v2 승인 |
  |---|---|---|---|
  | `bidops_rla_t11` | `e7018832-275f-4b5e-a2b6-1b1b151f16c1` | `5f0754e1-5b45-49ce-a661-7b82c433a2f9` | `60a18f7d-09c0-473e-ad91-119b18c549a8`(request `accd1d5e-88eb-4422-8bd0-83a30bd9d9fc`) |
  | `bidops_rla` | `7636ae7c-0b68-4e89-999c-0768e9302513` | `4829f92a-55e2-4103-950f-cfef3aa62341` | `ac1c1f4f-70f6-49d0-a239-85c08291197d`(request `2c7603de-8ccf-4b91-a0b6-6bbeab2969c2`) |

- **재실행**: `bidops_rla_t11`, mock provider, 참조 모드, 자동 트리거는 이 단계에서만 true. 자동 트리거는 3차에서 이미 실행됐다. 폴리텍은 이미 2026-10-16 브리핑 항목이라 다시 추천되지 않으므로 수동 경로를 썼다: `POST /api/opportunities/14/verdict-requests`(actor jechoi, `request_id=bd74db55-077e-46aa-bd2a-6242f598e1a4`) → 202 `attempt_id=754aa052-4401-4676-a14a-a77be762f670`, `status=queued`.
  - 요청 직전 v1 판정 보기: `is_current=false`, `stale_reasons=["policy_changed"]`.
  - 새 review `f4393e6e-c77a-4dd6-a2ca-2e72b6fa8b3d`(v2 행).
  - `verdict_request`: `started`·`manual`·jechoi. 감사: `verdict.request.manual`(human jechoi), `deep_review.auto_create`·`external_transfer_approved`(system:transfer-policy), `job.claim`, `job.completed`.
- **실행 결과**:
  - 동결 입력: selector `card-sections-v2`, unit 35, batch 5, `missing_sections=["contract"]`.
  - `card_analysis_stage`: extract 5·compare 5·role 3·synthesis 1. 완료 감사의 `call_count=9`(= B+4), `batch_count=5`, 약 0.39초.
  - WorkJob `completed`.
- **판정 보기** `GET /api/opportunities/14/verdict`:
  - 상태: `availability=completed`, `is_current=true`, `stale_reasons=[]`, `error_code=null`, `quality_status=mock_reference`.
  - 누락·연결: `missing_sections=["contract"]`, `briefing_item_id=ed381865-…`.
  - 결과: `result.verdict="판단 불가"`("진행 가능" 아님). mock 사유는 "모의 실행 결과이며 모델 판정이 아니다". 체크리스트 5행 모두 `unknown`, matrix 35행 모두 `unknown`, `next_actions` 0.
  - identity: v2 행, `gpt-6-luna`/high, CLI 0.162.1. 화면에서는 실행 정보 다이얼로그에서만 보인다.
- **활동** `GET /api/opportunities/14/activity`: `verdict_completed` "판정 완료 · 판단 불가"(링크 `/opportunities/14/verdict`)와 `pre_spec_opened`.
- **브리핑** `GET /api/briefings/2026-10-16`: `bidops.briefing.v2`, 폴리텍(10위) `verdict_display="판단 불가"`. 나머지 9건은 "분석 대기".
- **Slack**: 브리핑 항목 `slack_message_ts=null`이라 스레드 답글은 건너뛰었다. 오류 로그 없음. 실제 Slack 증명이 아니다(D5).
- **상한·전송**: `today_used=0`, `analysis.transfer.sent` 0건. 모델·runner·나라장터 호출 0.
- **아직 증명 못 한 것**: 준비 시작→ready hook 자동 경로(3차에서는 묶음이 이미 ready였다), cap 큐·drain, 화면 1280·1440. 결과는 `mock_reference`이고 품질 근거가 아니다.
- **뒤처리**:
  - T11 worker를 멈추고 `t11.env` 자동 트리거를 false로 되돌렸다.
  - rla-web은 `bidops_rla`로 돌아갔다(vllm, 자동 트리거 false, v2 행 `7636ae7c-…`).
  - rla-analysis-worker 컨테이너는 같은 실제 경로 설정으로 다시 만들기만 하고 시작하지 않았다.
  - 실제 경로 확인: `GET /api/opportunities/353/verdict`가 `none`, `today_used=0`, 묶음 `b5be84f0-bc57-4fae-9f9e-6665e7a3e790`이 `ready`, attempt 0.

### 5차 (결정 B30·B31 반영 뒤, 2026-10-17) — v3 정책으로 completed

- 이미지 재빌드: `bidops-local:rlb-20261017-rl03` = `sha256:0433eb96ff080ef4096674fde09d0b6b230277b67bf6a5452769516dc86d5420`.
  - 이미지 안 `analysis-policy-luna-rl-v3.json`의 sha256 = `635f673063ca1a92fb751aea6ffbdb76c54e0d70309b9f0a1e84d961fe192b12`.
  - migration head는 그대로 0040이고 권한 파일도 바뀌지 않았다.
  - runner 이미지(`sha256:780b65d9…`, 20:40 빌드)는 runner.py와 schema 5개가 worktree와 같아 다시 빌드하지 않았다.
- v3 정책 행 등록과 재승인(`bidops_rla_t11`, 모두 exit 0):
  - import 결과 행 `71f7f868-af02-44a2-bf19-4c40b908e070`. `t11.env`에서 이 행을 선택했다.
  - v2 승인 `60a18f7d-…`를 사유를 적어 철회했다.
  - v3 승인 `8cc4d654-7db5-4cab-b11d-68e116b6a1cf`(actor jechoi, cap 2, request `f42a534c-291a-40af-bac0-089c94967a4e`).
- 재실행 조건: mock provider, 참조 모드, 자동 트리거 false. 수동 요청 `POST /api/opportunities/14/verdict-requests`(actor jechoi, `request_id=9555fa85-136b-4d4f-80ef-415b3e502ffc`) → 202 `attempt_id=8acae770-45e6-4ead-97c1-5caf983cf2b1`, review `4339e3b0-9791-433d-942b-78c0d62f93bb`.
- 동결 입력:
  - selector `card-sections-v3`, unit **32**개, batch **4**개.
  - `missing_sections=["contract"]`.
  - 쪽번호 없는 목차 제목 unit이 빠져 v2 대비 unit이 35→32개로 줄었다.
- 실행 기록: stage는 extract 4·compare 4·role 3·synthesis 1. 완료 감사 `call_count=8`(= B+4), `batch_count=4`. WorkJob과 attempt 모두 `completed`.
- 판정 보기:
  - `availability=completed`, `is_current=true`, `stale_reasons=[]`, `missing_sections=["contract"]`, `error_code=null`, `quality_status=mock_reference`.
  - `result.verdict="판단 불가"`("진행 가능" 아님). matrix 32행과 체크리스트 5행이 모두 `unknown`.
  - identity의 정책은 v3 행이다.
- 활동: `verdict_completed` "판정 완료 · 판단 불가"가 4차·5차 두 건 남았다.
- 브리핑 2026-10-16: 폴리텍의 `verdict_display="판단 불가"`.
- 상한과 전송: `today_used=0`, `analysis.transfer.sent` 0건. 모델·runner·나라장터 호출 없음. 실행 뒤 T11 worker를 중지했다.
- 남은 한계: mock 결과라 품질 근거가 아니다. extract 지시가 실제 모델에서 통과하는지는 T12만 증명할 수 있다.

### 6차 (결정 B33·B34, 2026-10-18 KST) — v4 정책(extract 계약 v2)으로 completed

**이미지 두 개 재빌드.** 이미지 안 파일은 모두 worktree와 sha256이 같다.

| 이미지 | id | 확인한 파일 |
|---|---|---|
| `bidops-local:rlb-20261017-rl03` | `sha256:2e05694691a1d04f26632efc46d7908ec588b22fbdd6a53678a7f796f9e9afbf` | `analysis-policy-luna-rl-v4.json` `8cc623f280ca5d155073ecd261f5a2a1ecd3a8d497fc5aec9c815537923183d7`, `bidops.requirement-extract.v2.json` `1ff9487bfee68d8fd4b09261f90cca678608356827cd504033add09573709b6d`. migration head 0040 그대로, 권한 파일 불변 |
| `bidops-local:rlb-20261017-runner` | `sha256:78fe765f55d48620a30c977fbf5083acf3dc5c727ebb948c8bc257a707fb4061` | `/app/card-extract-v2.json` `1ff9487b…709b6d`, `/app/runner.py` `f7a8b1961a72b061476829697a8b04efc3f5b5a0215be633e55e679df512b552`, 기존 card schema 3개 sha 불변, `codex-cli 0.162.1` |

**v4 정책 등록과 재승인** (`bidops_rla_t11`, 모두 exit 0).
- v4 행 `ac78fe69-87bd-4a4d-a55b-aa27b0f2cfef`를 `t11.env`에서 선택했다.
- v3 승인 `8cc4d654-…`를 철회했다.
- v4 승인 `4cdb36ba-ba8d-456f-9171-8ddfa058f90a`(actor jechoi, cap 2, request `0e4b18dc-5fb3-4add-8742-7a1241d2a024`).

**재실행** (mock provider, 참조 모드, 자동 트리거 false).
- 요청: `POST /api/opportunities/14/verdict-requests`(actor jechoi, `request_id=f6fdc9c5-6866-4288-bc3b-4f7ee115122d`) → 202.
- attempt `2b3b1e52-19c2-4eb4-8b12-1fc7954c04b1`, review `6cc71ba1-7b51-4ea3-a282-884074b250cc`.
- 동결 입력: `card-sections-v3`, unit 32, batch 4, `missing_sections=["contract"]`.
- 단계: extract 4, compare 4, role 3, synthesis 1. extract 결과 item에는 코드가 채운 `concept_candidates`가 들어 있다.

**완료 감사** `deep_review.job.completed`:
- `call_count=8`, `batch_count=4`, `extract_contract="bidops.requirement-extract.v2"`
- `code_derived_fields=["concept_candidates","constraints.operator"]`
- `target_missed=false`, 약 0.6초. WorkJob `completed`.

**판정 보기** `GET /api/opportunities/14/verdict`:
- `availability=completed`, `is_current=true`, `stale_reasons=[]`
- `missing_sections=["contract"]`, `error_code=null`, `quality_status=mock_reference`
- 판정 "판단 불가"("진행 가능" 아님). matrix 32행과 체크리스트 5행이 모두 `unknown`.
- identity 정책은 v4 행이다.

**활동·브리핑**
- 활동: `verdict_completed` "판정 완료 · 판단 불가"(4·5·6차 누적 3건).
- 브리핑 2026-10-16: 폴리텍 `verdict_display="판단 불가"`.

**상한·전송.** `today_used=0`, `analysis.transfer.sent` 0건. 모델·runner·나라장터 호출은 없었다. 실행 뒤 mock worker를 멈췄다.

**한계.** mock 결과는 품질 근거가 아니다. extract v2 계약이 실제 모델에서 통과하는지는 T12만 증명한다.

### 7차 (결정 B35·B36, 2026-10-18 KST) — v5 정책으로 completed, mock이 실제 제약을 낸다

이미지 `bidops-local:rlb-20261017-rl03`을 다시 빌드했다(`sha256:dd720653a7427c7e7ce1da087d55a0ba9c44bede6da6f3d94d5215b8a6c6cad8`).
- 이미지 안 파일의 sha256은 worktree와 같다: `analysis-policy-luna-rl-v5.json` `19d7ff26fb9899f95237ec931c440bfad89feb42e3626fba89c33132f42928b2`, `card_analysis.py` `5a433bd24bd7444e0abcf54eec43442b3b5fc9c1539ab706e799d2d1cbe7d7f3`.
- migration head는 0040이고 권한 파일도 바뀌지 않았다.
- runner 이미지 `78fe765f…`는 그대로 썼다. runner.py와 extract v2 schema의 sha가 worktree와 같다.

v5 정책을 등록하고 다시 승인했다(`bidops_rla_t11`, 모두 exit 0).
- v5 행 `dbf062a3-0c23-46fa-a98d-49b3d60d2b3e`을 `t11.env`에서 선택했다.
- v4 승인 `4cdb36ba-…`를 철회했다.
- v5 승인 `09c42d16-003a-4afe-9c48-c1062c91e79c`을 만들었다(actor jechoi, cap 2, request `3bbf46ea-020a-4548-9ee3-a0c27add9c82`).

재실행 조건은 mock provider, 참조 모드, 자동 트리거 false다.
- `POST /api/opportunities/14/verdict-requests`(actor jechoi, `request_id=a05d1991-f1e8-4da8-8af7-c947f7eadf78`) → 202.
- attempt `be073e43-0332-42a3-8fde-46f9c96537ac`, review `ecae9fc7-3b58-465c-8825-ddcfc6be6d95`. WorkJob과 attempt 모두 `completed`.
- 동결 입력: `card-sections-v3`, unit 32, batch 4, `missing_sections=["contract"]`.
- 완료 감사: `call_count=8`, `batch_count=4`, `extract_contract=bidops.requirement-extract.v2`, `code_derived_fields=["concept_candidates","constraints.operator"]`.
- 단계 수: extract 4·compare 4·role 3·synthesis 1.

저장된 extract 단계의 제약 수 (batch마다 item 8개):

| batch | 제약 수 | 제약이 있는 item |
|---|---|---|
| 0 | 1 | 1 |
| 1 | 5 | 3 |
| 2 | 2 | 2 |
| 3 | 14 | 2 |
| 합계 | 22 | 8 |

제약 종류(kind·operator·unit, 건수):
- percentage·eq·percent 15, percentage·gte·percent 2, percentage·unknown·percent 1
- duration·gte·day 1
- amount·eq·KRW 1, amount·unknown·KRW 1
- count·eq·person 1

compare 32행은 모두 `unknown`이다. mock 제약은 회사 사실과 연결되지 않기 때문이다.

판정 보기 `GET /api/opportunities/14/verdict`:
- `availability=completed`, `is_current=true`, `stale_reasons=[]`, `error_code=null`.
- `missing_sections=["contract"]`, `quality_status=mock_reference`.
- 판정은 "판단 불가"이고 "진행 가능"이 아니다. matrix 32행과 체크리스트 5행이 모두 `unknown`이다.
- identity의 정책은 v5 행이다.

나머지 확인:
- 활동 맨 위에 `verdict_completed` "판정 완료 · 판단 불가"가 있다(4~7차 누적 4건).
- 브리핑 2026-10-16에서 폴리텍의 `verdict_display`는 "판단 불가"다.
- `today_used=0`, `analysis.transfer.sent` 0건. 모델·runner·나라장터 호출은 없었다. 실행 뒤 mock worker를 중지했다.

한계: mock 결과라 품질 근거가 아니다. 엄격해진 인용·비교어 검증을 실제 모델 출력이 통과하는지는 T12만 증명할 수 있다.

### 8차 (결정 B37, 2026-10-18 KST) — v6 정책으로 completed, 저장된 수치 인용은 모두 블록 안에서 유일

**이미지.** `bidops-local:rlb-20261017-rl03`을 다시 빌드했다(`sha256:4071cb951d102d1f1f09b0ae91c300676e62df138a2a7235bf96cf43b86d816b`).
- 이미지 안 `analysis-policy-luna-rl-v6.json`의 sha256은 `84e94954c08a43e5751d1514cf1a02e6865c9d6f05c6483777785e29faf8534a`, `card_analysis.py`는 `037822e00f26d001b4a9ff4f01edc6eb6e165f3e718f6c3210cf8de26d19643e`이다. 둘 다 worktree와 같다.
- migration head(0040)와 권한 파일은 바뀌지 않았다.
- runner 이미지 `78fe765f…`는 그대로다. runner.py sha가 바뀌지 않았고, runner는 시작하지 않았다.

**v6 정책 등록과 재승인** (`bidops_rla_t11`, 모두 exit 0).
- v6 행 `f3247812-0640-428c-b308-bc4b31b4d2d0`을 `t11.env`에서 선택했다.
- v5 승인 `09c42d16-…`를 철회했다.
- v6 승인 `3f8b5ad2-4a17-4f16-9f21-69a1d1f04ae4`를 만들었다(actor jechoi, cap 2, request `7ea81057-9023-4d55-a8b9-ce9eabb042a3`).

**재실행** (mock provider, 참조 모드, 자동 트리거 false).
- `POST /api/opportunities/14/verdict-requests`(actor jechoi, `request_id=7f58f92a-cc1f-4cd7-ba86-66ea4d523b03`) → 202.
- attempt `d57258e8-2643-4531-ae76-610c159c692f`, review `7394c066-be45-423a-b482-10113b295e25`. WorkJob과 attempt 모두 `completed`.
- 동결 입력: `card-sections-v3`, unit 32, batch 4, `missing_sections=["contract"]`.
- 단계 수: extract 4·compare 4·role 3·synthesis 1. 완료 감사 `call_count=8`, `batch_count=4`, extract 계약 v2.

**batch별 제약 수** (batch마다 item 8개)

| batch | 제약 수 | 제약이 있는 item 수 |
|---|---|---|
| 0 | 1 | 1 |
| 1 | 5 | 3 |
| 2 | 2 | 2 |
| 3 | 14 | 2 |
| 합계 | 22 | 8 |

**인용 유일성.** 저장된 제약 인용 22개를 원문 블록(structure `944579cd-…`)에서 하나씩 세었다. 22개 모두 그대로 비교해도 1회, 공백을 지우고 비교해도 1회 나온다.
- 숫자 뒤에 비교어가 붙은 인용(`5일 이상`, `99% 이상`, `85% 이상`, `90%를 초과`, `20억원 미만`)은 비교어까지 포함돼 있다.
- operator는 대응이 분명한 것만 `gte`이고 나머지는 `unknown`이다. `초과`는 `unknown`으로 남았다.

**판정 보기와 연결.**
- 판정 보기: `availability=completed`, `is_current=true`, `missing_sections=["contract"]`, `quality_status=mock_reference`.
- 판정은 "판단 불가"이고 "진행 가능"이 아니다. matrix 32행이 모두 `unknown`이다. identity는 v6 행이다.
- 활동에 `verdict_completed`가 남았다(4~8차 누적 5건).
- 브리핑 2026-10-16에서 폴리텍의 `verdict_display`는 "판단 불가"다.
- `today_used=0`, `analysis.transfer.sent`는 0건이다. 모델·runner·나라장터 호출은 없었다. 실행 뒤 mock worker를 중지했다.

**한계.** mock 결과는 품질 근거가 아니다. B37(옵션 B)에 따라 이 배치에서는 v6로 실제 호출하지 않는다.

### 실행하지 않은 확인 항목 (2차 시점 기록 — 이후 실행한 항목은 위 3·4차 절이 정본. 3차의 "T12도 같은 code로 끝난다" 예상은 v1 기준이며 v2에서는 해당하지 않는다)

| 확인 항목 | 상태 |
|---|---|
| 브리핑 추천 → 문서 준비 → ready hook → worker 역할 attempt 생성(`actor_kind=system`, 개요 run 0) | 미실행(막힌 것 1·2·3) |
| 같은 조합 재트리거 없음 / cap 큐·drain / 입찰공고·SW≠Y 미트리거 | 미실행 |
| `analysis.transfer.sent` 감사 | 미실행 |
| `GET /api/opportunities/{id}/verdict` 상태 전이·`card-v1` 현재성 | `none`만 확인 |
| 활동 `verdict_completed`·브리핑 `verdict_display`·Slack 스레드(가짜) | 미실행 |
| 화면 `/opportunities/:id/verdict` 1280·1440 | 미실행 |

재현: overlay·명령은 `.sdlc/local-runtime/rlb-20261017/`(Git 밖: `README-stack.md`·`rla-rl03.yml`·`compose.sh`·`rlb.env`, 로그 `logs/`). 한계: mock은 Luna 인증·모델 접근·실자료 품질을 증명하지 않으며 T11은 T12의 대체가 아니다.

## T12 실제 Luna 1건

상태: **pending** (사람 직전 확인 대상. 정책 승인 CLI·runner 재배포·bidops-local 스택 변경·실제 호출은 각각 짧게 알린 뒤 진행한다).

- 조건: 자동 트리거 off(`BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`·`BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`·`BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`), 수동 `POST /api/opportunities/{id}/verdict-requests` 1건, 폴리텍 사전규격(로컬 원본 HWP `~/orca/fixtures/RFP/`, 나라장터 호출 없음), 승인 `--daily-cap 2`(실행 1 + 재시도 1), attempt당 호출 약 B+4 ≤ 24, 검증 실패 시 **1회만** 다시 시도하고 그래도 실패면 정지·보고(RL-04 T11 보류).
- 대상 공고·원본 파일 sha(이전 수집본과 일치 확인): _pending_.
- 정책 행 `policy_version_id`·`policy_sha256`·승인 `approval_id`·`daily_cap`: _pending_.
- attempt id·sha·`input_sha256`: _pending_. 단계 수(extract·compare·role·synthesis)·호출 수·소요 시간(목표 2400초/강제 3600초): _pending_.
- `analysis.transfer.sent` 감사(건수·`planned_call_count`·`unit_count`): _pending_. 승인 감사 없는 전송·payload에 노트/`proposed`·`unknown` 값/운영 정보·상한 초과 여부: _pending_(정지 조건).
- 결과: availability·판정·체크리스트·"확인 필요" 비중: _pending_. **"확인 필요"가 많으면 루트랩 회사 근거의 `unknown` 21건이 원인인 데이터 상태로 적고(D13) 판정 실패로 읽지 않는다.** `quality_status=unmeasured_reference`.
- 재시도 여부와 사유: _pending_.
- 한계(채울 때 적는다): 1건 실행이며 품질·정확도를 측정하지 않았다. Slack 스레드는 토큰이 없어 가짜 서버 검사까지이고 실제 Slack 게시 증명이 아니다(D5).

### T12 1차 시도 (2026-10-17 11:26Z) — 실패, 원인 조사 중

- 사전: 승인 `ac1c1f4f-70f6-49d0-a239-85c08291197d`(v2 `e733e94a…`, cap 2, jechoi), `today_used=0`, `GET /api/opportunities/353/verdict`=none, 묶음 `b5be84f0-…` ready.
- runner `bidops-local-rla-codex-runner-1` 기동(인증 파일 경로만 전달), worker 기동, `POST /api/opportunities/353/verdict-requests`(jechoi, request `919c7ee2-1a68-42be-afb2-d5c6097120cc`) → 202 attempt `bc9e1c8f-9c84-4bfb-bfb3-d9339e51b7ab`.
- 결과: 11:26:12Z `failed`·`processing_failed`, 단계 행 0, `analysis.transfer.sent` 감사 1건(11:26:12.149Z) 직후 50ms에 실패, `today_used=1`. worker 로그에 traceback 없음, runner 로그 비어 있음. 모델 검증 실패가 아니라 worker 내부 오류로 판단하고 재시도 전에 원인을 조사한다(인터뷰 D10의 재시도 1회는 원인 수정 뒤 사용).

### T12 1차 원인과 조치 (2026-10-17)

- 원인: rla overlay runner URL `rla-codex-runner` ↔ LunaClient 고정 host `codex-runner` 불일치 → client 생성 ValueError(`processing_failed`). HTTP 호출 전이라 **실제 전송 0**(가짜 runner 재현으로 확인). 그런데 전송 감사가 먼저 기록돼 cap 1 소모.
- 조치(결정 B25): overlay에 `rla-luna-internal` 한정 별칭 `codex-runner`, 제품은 전송 감사 전에 runner 주소 검사(`runner_unavailable`, 감사·cap 없음) + 회귀 테스트. 승인 `ac1c1f4f…` 철회 → cap 3 재승인 `df307a3b-f229-4f2c-b854-c5f182478a70`(실제 전송 상한 2회 유지, B26).

### T12 2차 시도 (11:35Z) — 실제 전송 1, `runner_failed`

- request `9383ccd1-e679-4508-b863-1f47f13fb7a5`, attempt `beccbbf1-8d8e-4af6-a11a-8324ade03d1a`, `analysis.transfer.sent` 11:35:29Z(planned 9), 11:35:49Z `failed`·`runner_failed`, 단계 0. runner가 codex `--json` stdout 오류 이벤트를 버려 진단 불명 → 결정 B27로 범주 진단 추가.

### T12 3차 시도 (11:38Z, 승인 범위의 마지막 재시도) — `needs_human_review`·`card_extract_invalid`

- request `4f72e38b-2bad-4ff2-8f1b-a1f31320d5cd`, attempt `50829b45-6681-40bb-b22d-83196682c6b0`, runner 로그 `runner.call_failed` 2건(원 호출 + repair) `error_code=schema_invalid`, categories `["network","schema"]`, 단계 0, `today_used=3`(cap 3).
- 원인: card-extract(와 synthesis) 출력 schema의 `uniqueItems`를 strict structured output이 거부. 조치(결정 B28): runner가 디코딩용 schema에서 `uniqueItems` 제거, guard 테스트. **승인된 실제 전송(2회)을 모두 사용해 정지했고 RL-04 T11은 보류.** 추가 실제 호출은 사용자 승인 대기.
- 품질 표식: 실제 판정 결과 없음. 어떤 결과도 품질 근거로 쓰지 않는다.

### T12 4차 시도 (13:12Z, 사용자 추가 승인 1건, B29) — `needs_human_review`·`card_extract_invalid`

- 승인 `bb663c6b-4243-4e84-a9a4-a22c04a264fd`(cap 4), request `b8e19164-409b-4688-915e-f658534e33bb`, attempt `6dd54a57-fb94-4b4f-afa1-e2e3dacb2b3e`, `analysis.transfer.sent` 13:12:26Z(planned 9).
- runner 실패 로그 0(schema 문제 해소 확인). extract batch 0 응답 1건 저장(13:13:06Z, `response_sha256 c49eb3f1…`, 암호화 저장) 직후 BidOps 추출 검증이 거부 → `card_extract_invalid`, 단계 0. 자동 보정·추가 재시도 없음(사용자 조건). 실제 전송: 이 시도 1회 호출.
- 원인 진단은 저장된 응답을 오프라인으로 같은 검증기에 넣어 확인한다(외부 호출 없음).

### T12 5차 시도 (2026-10-17 19:06Z UTC = 10-18 KST, 정책 v3, 사용자 승인 1건 B32) — `needs_human_review`·`card_extract_invalid`

- 승인 `b6660a94-5e7a-4ad0-b914-70ca8aaca1b2`(v3 `635f6730…`, cap 5; KST 날짜가 바뀌어 today_used 0에서 시작), request `991a1a53-ab27-40c1-895b-2fe4dfcd72b7`, attempt `bd0fe0a3-1230-4270-99d4-d167ac8e5848`, `analysis.transfer.sent` 19:06:56Z(unit 32).
- runner 실패 0. extract batch 0 응답 1건 저장(19:07:42Z) 직후 추출 검증 거부, 단계 0. 사용자 조건대로 추가 시도 없음, runner·worker 정지. 원인은 오프라인 재생으로 진단 중.
- 오프라인 진단(재생 해시 일치, 외부 호출 없음): v3 지시는 거의 지켜짐 — unit당 item 8/8·순서 일치, expected_concepts 28쌍 100% 복사, 개념·인용·숫자 실패 0(v2는 item 11/14 실패). **실패는 제약 1개**: `다음 달 10일까지` → kind=count·unit=day·lte(검증기 kind×unit 표 위반, operator는 닫힌 어휘상 eq 기대). 이 제약만 고치면 통과.
- 남은 구조 원인: (1) kind×unit 규칙이 pydantic에만 있고 runner `--output-schema`에는 없어 생성 단계가 막지 못함, (2) pydantic 위반은 `schema_invalid`가 아니라 repair가 돌지 않음, (3) operator·개념처럼 결정적인 필드를 모델이 재현해야 함. 같은 표현(`N시간`·`N일 이내`·`N일까지`)이 batch 1~3에 다수.

### T12 6차 시도 (2026-10-17 22:01Z UTC = 10-18 07:01 KST, 정책 v4·추출 계약 v2, 사용자 승인 B33) — `needs_human_review`·`card_extract_invalid`

- 승인 `3616d95c-1856-4e44-8498-268cb354fa07`(v4 `8cc623f2…`, cap 2), request `c4620693-2daf-422e-a7c7-4a61cb76a957`, attempt `28086c87-6b5f-42b7-afd4-fc86bd49d929`, `analysis.transfer.sent` 22:01:41Z(unit 32), runner 이미지 `78fe765f…`.
- **batch 0 통과**(extract 1·compare 1 단계 저장, repair 없음) — 5차까지 실패하던 첫 묶음이 v2 계약으로 처음 통과. batch 1 응답(22:03:01Z, repair_attempt 0) 직후 검증 거부, repair 없이 실패 → 비구조(인용·숫자·개념·근거 계열) 위반으로 추정, 오프라인 재생으로 확인 중. runner 실패 0. 실제 호출 2회. 추가 시도 없음, runner·worker 정지, today_used 2/2.
- 오프라인 진단(재생 해시 일치, 외부 호출 없음): batch 1의 실패는 제약 1개 — `5일 이상의 업무 인계·인수기간`을 duration으로 내면서 인용을 `'5'`만 잘라 씀(v4 지시 "그 숫자만 담은 가장 짧은 부분문자열"을 문자 그대로 따른 결과). 인용·숫자·근거 위치 날조 0, 시간·`이내` 표현은 text로 올바르게 처리.
- **더 중요한 발견: 통과했지만 틀린 제약.** 짧은 인용 + 인용에서 operator 유도 때문에 `월 3회 미만`→eq, `90%를 초과`→eq, `9글자 이상`→eq, `10분 간격`→count 같은 제약이 검증을 통과했다. 비교 단계가 operator를 신뢰하므로 거부보다 나쁜 조용한 오류다. 이 결과(batch 0 단계 포함)는 품질 근거로 쓰지 않는다.
- mock은 제약을 0개 내므로 제약 규칙을 증명하지 못한다(가짜가 결함을 가린 사례).

### T12 7차 시도 (2026-10-17 22:55Z UTC = 10-18 07:55 KST, 정책 v5·강화 검증기, 사용자 승인 B35) — `needs_human_review`·`card_extract_invalid`

- 승인 `bc75dec9-bcf8-418d-8d1a-da65c9572f50`(v5 `19d7ff26…`, cap 3), request `e14bec1c-72d9-486a-b689-19072abec46f`, attempt `ff63bc6e-2444-45cb-9af2-f4a160cb765b`, `analysis.transfer.sent` 22:55:48Z(unit 32).
- batch 0 응답(22:56:28Z, repair 0) 직후 검증 거부, repair 없음, 단계 0. runner 실패 0. 실제 호출 1회. 추가 시도 없음, runner·worker 정지, today_used 3/3. 원인은 오프라인 재생으로 진단.
- 오프라인 진단(재생 해시 일치, 외부 호출 없음): v5 batch 0 실패는 제약 1개 — 기간 `2027. 1. 1. ～ 2027. 12. 31.`에서 모델이 "12개월"을 계산해 duration 값 12로 낸 실제 모델 오류(인용에 없는 숫자). 잘린 인용 실패 0, `월 1회`·`연 1회 이상`·`다음 달 10일까지`는 올바르게 인용.
- 검증기 결함 2건 확인: (1) 잘린 인용 검사가 블록 안 **모든 등장 위치**를 봐서, 6차 답의 정상 인용 `1회`(`월 1회`)가 같은 블록의 `연 1회 이상` 때문에 거부됨 (2) 범위 정규식이 `〜`(U+301C)와 `2027. 1. 1. ～` 형태를 놓쳐 `4〜8시간` 등이 eq로 통과(조용한 오류, batch 1에 12건).
- 전 묶음 숫자 스캔: 통과 가능한 인용은 항상 존재(불가능 0), 다만 최소 인용이 블록에서 반복되는 숫자가 batch 1에 16, batch 3에 12개.
