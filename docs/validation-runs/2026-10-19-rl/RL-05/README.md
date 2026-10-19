# RL-05 gold 인수 평가 준비 — bidops-local (격리)

2026-10-19, run `rlc-20261019`, 기능 `RL-05-gold-acceptance`. 사용자 gold 10건과 RL-03 판정을 대조하는 평가의 **표본 선정·홀드아웃·빈 gold 양식 준비까지**의 기록이다. **사람이 gold를 쓰기 전이고 모델 호출은 이 run에서 0회다. 채점 지표·사람 결정은 아직 없다.** 문서 원문·회사 자료·사람 답은 적지 않으며 sha256·건수·식별자만 적는다. 절차는 [operations.md "RL 판정 gold 인수 평가"](../../../operations.md#rl-판정-gold-인수-평가-rl-05-2026-10-19), 기준은 [model-quality-gate.md "RL 판정 gold 인수"](../../../model-quality-gate.md#rl-판정-gold-인수-rl-05)다.

- 환경: 격리 스택 `bidops-local`(운영 `bidops` 스택·운영 DB 미사용), DB `bidops_rla`, export용 이미지 `bidops-local:rlc-20261019-rl05`(feature worktree `81084a4`), web의 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`.
- 평가 디렉터리(Git 밖, `.sdlc/local-runtime/rl-evaluation-20261019/`)의 파일은 저장소에 두지 않는다. 사람이 쓸 작업 양식은 같은 디렉터리 `worksheet/` 아래다.

## 후보와 선정 (사용자 결정 C6·C8)

| 단계 | 결과 |
|---|---|
| 후보 조회 | 운영 스택 읽기 전용 REST. 개요 `completed`·첨부 취득 전부 `완료`·SW사업대상=Y인 사전규격 **65건**, 그중 분석 원문이 하나뿐인 묶음 **58건**(원문이 여럿이면 export `selection_mismatch`) |
| 선정(C6) | 사용자가 추천 10건을 골랐다 |
| 교체(C8) | 추천 #56 `R26BD00281853`은 **요구사항 카드 0개**(요구사항 ID 표 없음)라 카드 상태 표본 10을 채울 수 없었다. 먼 분류 후보 3건의 카드 수(23·25·39)를 본 뒤 #15 `R26BD00284827`로 교체했다 |

최종 `document_id`와 요구사항 카드 수(`cards.json` 순서 = `document_id` 순):

| document_id | 카드 수 |
|---|---|
| R26BD00283840 | 38 |
| R26BD00283874 | 59 |
| R26BD00283915 | 68 |
| R26BD00284019 | 37 |
| R26BD00284080 | 46 |
| R26BD00284697 | 58 |
| R26BD00284717 | 46 |
| R26BD00284827 | 23 |
| R26BD00284941 | 46 |
| R26BD00284956 | 26 |

10건 모두 카드 10개 이상이다(최소 23).

## 격리 DB 준비

| 항목 | 결과 |
|---|---|
| 회차 적재 | `lifecycle-20261014-notices`를 바이트 그대로 복사(파일 11개, sha256 대조 일치) → `python -m app.lifecycle.ingest.cli --run … --collection`. run `lifecycle-20261014-notices--20261014T231311.542084Z`, 공고 441건. 경고 `opportunity_link_target_missing` 330·`screening_results_missing` 1 — 격리 DB에 사업기회 연결 대상·선별 결과가 없어 예상된 경고다 |
| 원문 | 운영 객체 백업 `20261019T0120Z`의 source namespace에서 **버전이 맞는** 객체를 복사했고 sha256이 운영 DB `content_object` sha256과 같음을 확인했다. `attach-local-original`(dry-run 선행)로 **13건** 연결(선정 10 + 교체된 #56 + 미사용 대체 후보 2). 전부 ClamAV clean, 묶음 `ready`. G2B 호출 없음 |
| 홀드아웃 | `drain-verdict-queue --hold … --reason gold_holdout`: `verdict_request` **13행** `rejected`·`gold_holdout`(연결한 13건 전부). 선정 공고의 RL review **0건** |
| binding | `company_sha256` `a638050fb0a886868f1a2f19d59be8445688b12ea065a2c32f2f0cc944b228f0`(루트랩 활성 graph), `ontology_sha256` `4d0f95c274e18c5774d9254f6d36a8125ade2844b7b2ff2a6593f95a001d7a15`(`bidops.company-ontology.rl-v2`). PDF 스냅샷이 없어 page map 없음 → `page_map_sha256` null |

## 평가 파일 (Git 밖, sha256 앞 16자)

| 파일 | sha256 접두 | 비고 |
|---|---|---|
| `selection.v1.json` | `4125e7f5f554f5ec` | 문서 10건·위 binding |
| `cards.json` | `1b86634fcc24f6d2` | `export-evaluation --cards` + `rl-gold.py export-cards` 결과 |
| 빈 `gold.v1.json` | `3e6aa74e00e04a55` | `rl-gold.py blank-gold`, 사람이 쓰기 전 양식 |

`rl-gold.py gold-check`를 빈 양식에 돌리면 `human_gold_incomplete`(exit 2)다 — 아직 아무도 쓰지 않았다는 **예상된 결과**이며 통과가 아니다.

## 현재 상태와 다음 단계

- 상태: 사람의 gold 작성(STEP-004)을 기다린다. `validating` 이전에 모델 실행·채점·인수는 하지 않았다.
- 이후 순서(각각 따로 확인): 사람이 모델 전에 gold 작성 → `gold-check` 통과 → 공고별 수동 RL-03 실제 분석(RL-03 정책 단위 승인과 요청 직전 사람 확인, 실제 Luna 전송) → `export-evaluation --actual`(초안) → 사람이 alignment → 최종 export → `rl-gold.py score` → 사람이 `acceptance.json`에 결정 기록. 이 기록에 파일 sha256·metrics·결정을 덧붙인다.
- metrics: **없음.** 모델 호출 수: 이 run에서 0.
- 이후 결과는 모두 `unmeasured_reference`이며 사람이 `accept`하기 전까지 품질 근거가 아니다. 표본 10건·실회사 1곳이므로 통과해도 운영 품질 보증이 아니다.

## 회사 근거 v3 반영 (2026-10-19, gold 작성 전)

- 인터뷰 §G 답: G1 직접생산 세부품명 3개 보유, G3 PM 8명(공공 PM 경력 분포), G4 ISMS, G2 나라장터 계약정보(사용자 지시, 활용신청 뒤 호출 74회)로 홈페이지 실적 7건의 계약금액·기간·역할(`company-profile.md` §8.2.1). 등록 파일은 공개문서 origin을 받지 않아 origin은 `user_interview`, 근거 계약번호는 값(`scope`)과 문서에 기록(결정 C10).
- `rootlab.source.v3.json`(Git 밖, sha256 `0ed2b5792bb0…`) import → graph `107523c55ce4…`(version `bee3042e…`), activate → binding revision 3. 상태: confirmed 129·proposed 1·unknown 18(v2 대비 unknown 3건 감소).
- binding이 바뀌어 사람 입력 전 파일을 `superseded-company-v2/`로 보존하고 다시 만듦: selection.v1.json `383eaa8ba6679471…`, cards.json `1b86634fcc24f6d2…`(카드 동일), blank gold.v1.json `09c830b995dfea40…`. gold-check = `human_gold_incomplete`(예상).
- 같은 날 Mac 재부팅으로 운영·격리 스택이 멈춰 사용자 확인 뒤 같은 컨테이너로 재기동(운영 health 200·C-2 v5 daily-trigger ON·preflight ok·tailnet serve 유지).

## 회사 근거 v4와 gold 초안 (2026-10-20)

- v4: 정보통신공사업(0036) 등록(사용자 확인)을 `qual:procurement_1468:extra_industries`에 반영 → `rootlab.source.v4.json`(sha256 `78f525bcae47…`), graph `402a9e06612c…`(version `a3334d97…`), binding revision 4, confirmed 130·proposed 1·unknown 17. AI 에이전트 플랫폼·AI 음성/모바일 앱 역량은 온톨로지 concept이 없어 미반영(결정 C12, 데이터 공백). 사람 입력 전 파일은 `superseded-company-v3/`, 새 selection `f7cb743a4688ee6a…`(카드 동일).
- gold 작성 방식(결정 C13): 사용자 요청으로 Claude가 문서별 초안을 쓰고(평가 대상 Luna와 독립, Luna 실행 전), 판정이 갈리는 지점을 사용자에게 확인받는다. 확인 답: 대구 외 상주 = 차단, 증명서 유효기간·SW사업자 확인서 세부 = 모름, 정보통신공사업 등록 있음, HW 유지관리 = 제외 분야, 6번 플랫폼 보유, 3번 AI·앱 자체 개발 가능, 2번 도메인 경험 모름, 충족 기준 엄격(HP §7). 차단 조건은 gap만(결정 C11).
- 후보: 진행 어려움 5·조건부 진행 5, `gold-check` structurally_valid. 최종 `gold.v1.json`은 사용자 확정 시각을 `authored_at`으로 기록한다.
