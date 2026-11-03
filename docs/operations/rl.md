# 루트랩 회사 근거·판정·제안서·평가

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

0041과 RL 코드는 2026-10-19 운영에 배포됐지만 분석은 비활성이다. 아래 절차는 격리 환경에서 검증한 실행 방법이다. 현재 정책 기본값은 v11, RL-04 실제 초안은 partial(4/6절), RL-05 인수는 reject다. 근거는 [현재 현황](../tracking/status.md)을 따른다.

## 회사 근거 갱신 (RL-00, 2026-10-16)

루트랩 회사 근거는 화면에서 고치지 않는다. 회사 파일을 고쳐 새 버전으로 다시 등록한다(이전 버전과 binding 이력은 불변). 원본 파일은 Git 밖 `~/orca/fixtures/company/rootlab/`(`ontology.v2.json`, `rootlab.source.v1.json`)이며 출처·sha256 기록은 `docs/validation-runs/2026-10-16-rl/RL-00/README.md`다. 값은 회사소개서·홈페이지·선호 조건·인터뷰 문서에 있는 확인됨·추정값·확인 필요만 옮기고 새 사실을 만들지 않는다.

1. **파일 수정.** 확인된 값은 해당 `unknown` 노드를 `confirmed`(값·source_ref 채움)로 바꾸거나, `proposed` 노드를 사람이 확인한 뒤 `confirmed`·origin을 확인 출처(`user_interview` 등)로 바꾼다. `proposed`는 origin `agent_proposal`만, `user_interview`는 `confirmed`·`unknown`만, `company_brochure`·`homepage`는 `confirmed`만 허용된다. 한글 이름은 `label`에만 두고 id는 ASCII다.
2. **`--dry-run`.** `python -m app.deep_review.cli import-company-knowledge --ontology <ontology.v2.json> --company <rootlab.source.v1.json> --actor <이름> --dry-run`. DB·객체·모델 쓰기가 없다. exit 0이고 `errors=[]`, `is_fictional=false`, `status_counts`(confirmed·proposed·inferred·unknown)가 수정 의도와 맞는지 본다. exit 2면 `source_invalid`(조합·origin·value 형태)이거나 `real_company_exists`(다른 slug의 실회사가 이미 있음)다.
3. **import.** 같은 명령에서 `--dry-run`만 뺀다. 같은 파일이면 같은 버전이고(`created=false`), 내용이 바뀌면 새 graph·profile version이다. import는 자동 활성화하지 않는다. 출력의 `graph_version_id`를 적어 둔다.
4. **activate.** `python -m app.deep_review.cli activate-company-knowledge --company-id <uuid> --graph-version-id <uuid> --actor <이름>`. binding revision이 오르고 이전 binding 이력이 남는다.
5. **확인.** `GET /api/company`의 `active_graph_version.graph_version_id`가 방금 활성화한 값인지, `GET /api/companies/{company_id}/profile`의 facts 수가 `status_counts` 합과 같고 origin·status가 의도한 값인지 본다. `GET /api/workload`의 `company_attention`은 `proposed`+`unknown` 합과 같아야 한다. 이전 버전은 `profile?graph_version_id=`로 계속 조회된다.
6. **기록.** README에 새 파일 sha256(`source_sha256`·`graph_sha256` 포함)·`status_counts`·변경 사유를 덧붙인다.

CLI는 web 이미지 안에서 돈다. fixture 디렉터리를 읽기 전용으로 마운트한 일회용 컨테이너로 실행한다(예: compose overlay에 `~/orca/fixtures/company/rootlab:/fixtures/rootlab:ro`를 둔 서비스로 `docker compose ... run --rm --no-deps -T <서비스> python -m app.deep_review.cli import-company-knowledge --ontology /fixtures/rootlab/ontology.v2.json --company /fixtures/rootlab/rootlab.source.v1.json --actor <이름>`). 2026-10-16 RL-00 STEP-006은 `bidops-local` 안의 별도 DB `bidops_rla`(기존 `bidops` DB는 HP-03 migration 0039에 있어 main 계열과 이력이 갈라졌다)에서 이 방식으로 import→activate→REST 확인을 했다(README 참조).

운영 DB에서 import·activate를 실행하는 것은 **직전에 사람 확인을 받는다.** dry-run은 쓰기가 없지만 확인 없이 활성화하지 않는다. 격리 스택(`bidops-local`)에서 먼저 같은 순서로 확인하고 운영 반영은 별도 승인이다. 가상회사 파일은 `BIDOPS_DEMO_ENABLED=true`가 아니면 import·`--dry-run` 모두 `fictional_requires_demo`(exit 2)로 거부된다. "곧 만료" 기준일 수는 `BIDOPS_COMPANY_EXPIRY_WARNING_DAYS`(기본 60, 1..365)다.

## RL 카드 판정 운영 (RL-03, 2026-10-17)

사전규격을 카드·영역 단위로 추출·대조·판정하는 RL-03의 실행·설정·승인 절차다(규칙은 [business-rules.md "RL 자동 분석과 판정 상태"](../business-rules.md), 계약은 [RL 계약 "카드 기반 참여 판정"](../contracts/rl.md#카드-기반-참여-판정-rl-03-2026-10-17)). 구현·mock 및 실제 모델 검증은 `bidops-local` 격리 스택에서 수행했다. 코드는 2026-10-19 운영에 배포됐으나 RL 분석은 비활성이다. mock 전체 경로(T11)와 실제 Luna 1건(T12)의 결과는 [검증 기록](../validation-runs/2026-10-17-rl/RL-03/README.md)에 적으며 그 기록이 없거나 pending이면 실행하지 않은 것이다. 실제 호출 결과는 `unmeasured_reference`이며 품질·운영 완료 근거로 쓰지 않는다. **모든 단계는 기본 꺼짐이고 아래 승인·플래그를 사람이 직전 확인 후 하나씩 켠다.** 앞 단계의 확인은 다음 단계로 이어지지 않는다.

**플래그.**

| 키 | 기본 | 역할 |
|---|---|---|
| `BIDOPS_RL_ANALYSIS_ENABLED` | `false` | 사업기회 판정 REST·실회사 판정 게이트 개방. 꺼져 있으면 `/api/opportunities/{id}/verdict*`·`/api/analysis/transfer-policy`가 404이고 브리핑 판정 표시·활동 피드 제공자는 아무것도 주지 않는다 |
| `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED` | `false` | 브리핑 추천→자동 시작과 `drain-verdict-queue`. 꺼져 있으면 hook과 drain이 아무것도 읽거나 쓰지 않는다 |
| `BIDOPS_RL_ANALYSIS_POLICY_PATH` | `policies/analysis-policy-luna-rl-v11.json` | import 원본 파일(immutable). 기본값은 결정 B23 전 v1, B30 전 v2, B33 전 v3, B35 전 v4, B37 전 v5, B51 전 v6, B53 전 v7, B55 전 v8, C15 전 v9, C20 전 v10이었고 v1~v10 파일은 그대로 남는다. 승인 CLI는 이 파일의 identity·sha를 선택 행과 대조하므로 **선택 행과 같은 버전**을 가리켜야 한다(v1·v2 행을 계속 쓰면 그 파일 경로를 명시) |
| `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID` | 없음 | import한 정책 행 선택. 비어 있으면 RL 경로 fail closed(`analysis_policy_unavailable`). demo용 선택 env와 별개 |
| `BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED` | 기존 | **RL 경로도 요구한다**(변경 없음, 결과가 참조 실행 표식) |
| `BIDOPS_PRESPEC_OVERVIEW_ENABLED`·`BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED` | `false` | RL 판정은 개요를 쓰지 않는다. 실제 호출 스택에서는 둘 다 `false`로 둬 개요 모델 호출이 생기지 않게 한다 |

기반 compose는 RL 키를 전달하지 않는다. 키는 web과 `worker` DB 자격으로 도는 서비스(`analysis-worker`·`prespec-attachment-worker`)가 **모두 같은 값**으로 읽어야 하므로 env 파일·overlay로 주고, 올린 뒤 `docker compose exec -T <서비스> printenv BIDOPS_RL_ANALYSIS_ENABLED`처럼 서비스마다 값 하나씩 확인한다.

**1. 배포 전제(운영 변경이므로 직전에 사람 확인).** migration `0040_card_analysis`(테이블 4개 + `briefing_item.slack_message_ts`, [contracts.md](../contracts.md))와 `scripts/runtime-privileges.sql`의 새 권한(worker INSERT 5개 포함)을 적용하고 `web`·`analysis-worker`·`codex-runner` 이미지를 새로 올린다. 전체 백업과 `before-rl-verdict-<날짜>` 롤백 태그를 먼저 남기고 migration head를 기록한다. 새 테이블은 DELETE 권한이 없어 되돌리려면 백업으로 복구한다. 회사 근거(RL-00)의 활성 binding이 먼저 있어야 한다(없으면 `company_profile_not_ready`).

**2. 정책 import와 선택.** 정책 행은 승인 대상이자 선택 대상이다. 파일을 고쳐 쓰지 않고 immutable 파일을 import한다.

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli import-profile-policy \
  --policy /app/web/backend/app/deep_review/policies/analysis-policy-luna-rl-v11.json \
  --label analysis-policy-luna-rl-v11 \
  --expected-policy-sha256 8dabbbb473f81d91f5bffb73ea56cafb92876a80680f4d0b376bad245c1cf45a --actor '<담당자 이름>'
# 출력의 policy_version_id를 BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID로 env에 넣고 web·worker 서비스를 재생성한다.
# 이미지에 company-profile.md가 없으면 --profile 로 읽기 전용 마운트한 사본을 준다(2026-10-20 RL-05에서 확인).
# v10 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v10.json --label analysis-policy-luna-rl-v10
#   --expected-policy-sha256 fcfb08ce95887ce51c8454b54c2c51c9ac1ca9c4df63ff1544862387a8130409
# v9 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v9.json --label analysis-policy-luna-rl-v9
#   --expected-policy-sha256 afaba1d3b41177828443cb8e736e9b4728619a07fdfff2241ecb12d505fd2984
# v8 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v8.json --label analysis-policy-luna-rl-v8
#   --expected-policy-sha256 63ca5b691bb87822839193d4b33d0af7a6c7b9569faa86e9345da88ca5857d4c
# v7 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v7.json --label analysis-policy-luna-rl-v7
#   --expected-policy-sha256 2ba1d631b02d71b7c5fca251634bdc756c23b0308226ff14c741da5c2a631710
# v6 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v6.json --label analysis-policy-luna-rl-v6
#   --expected-policy-sha256 84e94954c08a43e5751d1514cf1a02e6865c9d6f05c6483777785e29faf8534a
# v5 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v5.json --label analysis-policy-luna-rl-v5
#   --expected-policy-sha256 19d7ff26fb9899f95237ec931c440bfad89feb42e3626fba89c33132f42928b2
# v4 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v4.json --label analysis-policy-luna-rl-v4
#   --expected-policy-sha256 8cc623f280ca5d155073ecd261f5a2a1ecd3a8d497fc5aec9c815537923183d7
# v3 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v3.json --label analysis-policy-luna-rl-v3
#   --expected-policy-sha256 635f673063ca1a92fb751aea6ffbdb76c54e0d70309b9f0a1e84d961fe192b12
# v2 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v2.json --label analysis-policy-luna-rl-v2
#   --expected-policy-sha256 e733e94a02b1240794ac50b7397d3974fb241917cf73fdeed009ba4ba0c4ff3b
```

이하 v1~v11 전환 메모는 기존 행·실행을 보존하는 버전별 차이다. 신규 설치는 위 v11 import 절차를 사용하며 옛 버전을 차례로 활성화하지 않는다.

**v1 → v2 전환(결정 B23).** v2(`card.selector="card-sections-v2"`)는 기호·사설 영역 불릿 제목(실제 HWP의 U+F06D 등)도 영역 제목으로 보고, 원문에서 찾지 못한 영역이 있어도 종합까지 가서 `missing_sections`를 기록한다(누락이 있으면 판정은 `진행 가능`이 될 수 없다). v1 행으로 이미 만든 판정·승인은 그대로 남는다. 전환 순서: (1) 위 명령으로 v2 import(행 canonical sha = 파일 sha `e733e94a…ff3b`), (2) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v2 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v2 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`를 재생성하고 서비스마다 값을 확인, (3) **아래 3단계로 v2를 다시 승인**한다 — 승인은 정책 행 sha 단위라 v1 승인은 v2 행에 쓰이지 않는다(승인 없으면 `policy_not_approved`). 일일 상한 `today_used`는 v1·v2 행을 합쳐 센다. 선택 행을 바꾸면 v1 행으로 만든 판정은 현재성 사유 `policy_changed`로 "과거 기준"이 된다. import·선택 변경·승인은 각각 직전에 사람 확인을 받는다.

**v2 → v3 전환(결정 B30).** v3(`card.selector="card-sections-v3"`)는 쪽번호 없는 목차 항목과 본문 없는 제목 unit을 원문 unit에서 빼고, 추출 지시문에 검증 계약(unit당 item 하나·입력 순서, 개념은 payload의 `expected_concepts` 그대로 복사, 날짜·인원·operator 규칙, 중복 금지)을 명시하며, 추출 payload의 unit마다 코드가 계산한 `expected_concepts`를 싣는다(검증기는 그대로, [RL 전송 payload 규칙](../contracts/rl.md#전송-payload-규칙-d2b10b11)). runner·runner contract·migration은 바뀌지 않아 web·`analysis-worker` 이미지만 새로 올린다. 전환 순서는 v1 → v2와 같다: (1) 위 명령으로 v3 import(행 canonical sha = 파일 sha `635f6730…2b12`), (2) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v3 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v3 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`를 재생성하고 서비스마다 값을 확인, (3) **v2 승인을 철회(`revoke-transfer-policy`, 사유 기록)하고 아래 3단계로 v3를 다시 승인**한다(`--policy analysis-policy-luna-rl-v3`; 승인은 행 sha 단위라 v2 승인은 v3 행에 쓰이지 않는다). `today_used`는 v1·v2·v3 행을 합쳐 세므로 같은 날 다시 승인할 때는 이미 쓴 수를 반영해 `--daily-cap`을 정한다. 선택 행을 바꾸면 v2 판정은 `policy_changed`로 "과거 기준"이 된다. 실제 호출 전 mock 경로(T11)를 v3 행으로 먼저 다시 돌리고, 추가 실제 호출은 다시 사용자 승인을 받는다(결정 B30). import·선택 변경·철회·승인은 각각 직전에 사람 확인을 받는다.

**v3 → v4 전환(결정 B33).** v4는 selector `card-sections-v3`를 유지하고 추출 출력 계약을 `bidops.requirement-extract.v2`로 바꾼다: 모델은 의미 필드만 내고(개념 후보·operator 없음) 코드가 그 둘을 채운 뒤 바뀌지 않은 검증기로 판정하며, kind×unit 규칙이 출력 schema에 있어 위반하면 규칙 코드와 item 번호만 담은 repair 1회를 받는다([RL 정책·단계 계약](../contracts/rl.md#정책단계-contract)). **runner 이미지도 다시 빌드해야 한다**(새 schema 파일 `/app/card-extract-v2.json`과 contract `card-extract-v2` 허용 목록). web·`analysis-worker` 이미지도 새로 올린다. migration은 없다. 순서: (1) runner·web 이미지 재빌드(직전 사람 확인), (2) 위 명령으로 v4 import(행 canonical sha = 파일 sha `8cc623f2…83d7`), (3) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v4 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v4 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`·runner를 재생성하고 서비스마다 값을 확인, (4) v3 승인을 철회하고 `--policy analysis-policy-luna-rl-v4`로 다시 승인(같은 날이면 `today_used`를 반영해 `--daily-cap` 결정), (5) mock 경로(T11)를 v4 행으로 먼저 돌리고, 실제 호출은 사용자 승인 범위(B33: 폴리텍 1건, 정상 8회·최대 16회, 실패 시 정지) 안에서만 한다. 선택 행을 바꾸면 v3 판정은 `policy_changed`로 "과거 기준"이 된다. 각 단계는 직전에 사람 확인을 받는다.

**v4 → v5 전환(결정 B35).** v5는 v4와 같은 추출 출력 계약(v2)·selector를 쓰고 추출 지시문만 바뀐다(숫자 제약은 숫자+단위+붙은 비교어를 그대로 인용, 분·초·글자·시간·간격은 text). 같은 배포에 들어간 검증기 강화(잘린 인용 거부, `까지`·`내에` → `lte`)는 **모든 정책 버전에 적용**되므로, web·`analysis-worker` 이미지를 올리면 v1~v4 행의 새 실행에도 바로 효력이 있다(이미 저장된 단계 행은 다시 검증하지 않는다). **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음; B33 runner 이미지 그대로). 순서: (1) web·`analysis-worker` 이미지 재빌드(직전 사람 확인), (2) 위 명령으로 v5 import(행 canonical sha = 파일 sha `19d7ff26…28b2`), (3) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v5 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v5 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`를 재생성하고 값 확인, (4) v4 승인 철회 → `--policy analysis-policy-luna-rl-v5`로 재승인(같은 날이면 `today_used` 반영), (5) mock 경로(T11)를 v5 행으로 먼저 돌린다(mock이 이제 숫자 제약을 낸다), (6) 실제 호출은 B35 승인 범위(폴리텍 1건, 정상 8회·최대 16회, 실패 시 정지) 안에서만. 각 단계는 직전에 사람 확인을 받는다.

**v5 → v6 전환(결정 B37).** v6는 v5와 같은 계약·selector에 추출 지시문만 바꾼다(숫자 인용은 block 안에서 유일하게 — 반복되면 왼쪽 단어를 붙임, 날짜 범위는 text이고 계산한 숫자 금지). 같은 배포의 검증기 수정(인용 유일성 `constraint_quote_not_unique`, 잘린 인용은 인용된 한 자리만 검사, 범위 `〜`·`.`/`)` 뒤 물결·숫자 사이 하이픈 → `unknown`)은 **모든 정책 버전에 적용**된다. **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음). 순서는 v4 → v5와 같다: web·`analysis-worker` 이미지 재빌드 → v6 import(행 canonical sha = 파일 sha `84e94954…534a`) → 선택 env 변경·재생성·값 확인 → v5 승인 철회·`--policy analysis-policy-luna-rl-v6` 재승인 → mock 경로(T11) 확인. 각 단계는 직전에 사람 확인을 받는다. **v6로는 실제 호출을 한 적이 없다**: 결정 B37로 이 배치의 실제 호출은 끝났고 RL-03 실제 증명(T12)은 pending이다. 다음 실제 호출은 새 사용자 승인 대상이다.

**v6 → v7 전환(결정 B51, 항목 단위 격리).** v7은 v6와 같은 추출 지시·계약·selector에 종합 지시문의 `rejected_units` 규칙만 더한다. 격리(증거 규칙을 어긴 항목만 "검증 실패 — 사람 확인 필요"로 빼고 판정을 이어감, 25% 초과면 판정 실패)는 **v7 이후 행(v7·v8·v9)에서만** 켜지고 v1~v6 행은 지금처럼 묶음 단위로 실패한다. 판정 보기 REST에 `rejected_units`와 matrix 행 `rejected_rule_codes`가 더해지고 판정 탭에 목록이 보인다(가산, migration 없음). **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음). web·`analysis-worker`와 프런트 이미지를 새로 올린다. 순서는 v5 → v6과 같다: 이미지 재빌드 → v7 import(행 canonical sha = 파일 sha `2ba1d631…1710`) → 선택 env 변경·재생성·값 확인 → v6 승인 철회·`--policy analysis-policy-luna-rl-v7` 재승인(같은 날이면 `today_used` 반영) → mock 경로(T11) 확인 → 실제 호출은 B51 승인 범위(폴리텍 1건 + 검증 실패 시 재시도 1회, attempt당 정상 8회·최대 16회) 안에서만. 각 단계는 직전에 사람 확인을 받는다. 판정 탭에 격리 목록이 있으면 담당자가 해당 요구사항을 원문으로 확인한다(자동으로 고치지 않는다).

**v7 → v8 전환(결정 B53).** T12 8차에서 운영·위험 역할이 같은 unit의 제약 인용(추출에서 원문 일치 검증 통과)을 근거로 써 `card_role_invalid`가 났다. 검증기는 이제 **모든 정책 버전**에서 unit별로 item evidence ∪ 그 unit 제약의 locator+quote를 허용하고(다른 unit·원문과 다른 문자열은 계속 거부), v8은 v7과 같은 규칙에 역할·종합 지시문 한 문장만 더한다. web·`analysis-worker` 이미지만 새로 올리고 **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음), 판정 보기 모양 변화 없음(프런트 재배포 불필요). 순서: 이미지 재빌드 → v8 import(행 canonical sha = 파일 sha `63ca5b69…7d4c`) → 선택 env 변경·재생성·값 확인 → v7 승인 철회·`--policy analysis-policy-luna-rl-v8` 재승인(같은 날이면 `today_used` 반영) → mock 경로(T11) 확인 → B51 승인 범위의 남은 재시도 1회는 v8로. 각 단계는 직전에 사람 확인을 받는다.

**v8 → v9 전환(결정 B55, 종합 출력 계약 v2·종합만 다시 실행).** T12 9차(v8)는 역할 3개까지 통과하고 종합이 역할 밖 대상·차단 조건 범위를 어겨 `card_synthesis_invalid`였다. v9는 추출·역할을 v8과 byte 동일하게 두고 종합 출력 계약을 `bidops.practitioner-verdict.v2`(차단 조건 없음 — 코드가 필수 gap으로 계산, 누락 영역·격리 unit "사람 확인" 행은 코드가 붙임)로 바꾼다. **runner 이미지를 다시 빌드해야 한다**(새 schema 파일 `/app/card-synthesis-v2.json`·contract `card-synthesis-v2` 허용 목록). web·`analysis-worker`·프런트 이미지도 새로 올린다(판정 보기 `next_actions[].origin` 가산·판정 탭 "사람 확인" 표식). migration·권한 변경은 없다. 순서: (1) runner·web·프런트 이미지 재빌드(직전 사람 확인), (2) v9 import(행 canonical sha = 파일 sha `afaba1d3…2984`), (3) 선택 env를 v9 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v9 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`·runner 재생성·값 확인, (4) v8 승인 철회·`--policy analysis-policy-luna-rl-v9` 재승인(같은 날이면 `today_used` 반영), (5) mock 경로(T11, v9·mock 실패 종합 뒤 resume) 확인, (6) 실제 호출은 새 사용자 승인 범위 안에서만 — 종합만 실패한 v8 attempt는 아래 요청으로 **종합만** 다시 실행할 수 있다(검증된 추출·대조·역할 행 재사용, 호출 1회, 상한 1; 전제 조건이 하나라도 어긋나면 409 `resume_source_invalid`이고 아무것도 남지 않는다). 각 단계는 직전에 사람 확인을 받는다.

```bash
# 종합만 다시 실행(결정 B55): 실패 attempt id는 판정 보기 ⋯ 실행 정보 또는 GET …/verdict의 attempt_id
curl -sS -X POST "http://127.0.0.1:<web 포트>/api/opportunities/<opportunity_id>/verdict-requests" \
  -H 'Content-Type: application/json' -H 'X-BidOps-Actor-Name: <담당자 이름>' \
  -d '{"request_id":"<새 UUID>","resume_from_attempt_id":"<실패 attempt id>"}'
# 202 {request_id, attempt_id, status:"queued"} → worker 처리 뒤 GET …/verdict 로 완료 확인.
# 확인: card.resume.requested·card.stages.reused 감사, analysis.transfer.sent planned_call_count=1,
#       GET /api/analysis/transfer-policy today_used가 1 늘었는지.
```

**v9 → v10 전환(결정 C15·C16).** 새 실행은 v10이 v9를 대신한다(v9 행·attempt·승인 기록은 그대로 남고, v9 → v10은 종합만 다시 실행의 계보가 아니다). v10은 큰 영역 분할(selector `card-sections-v4`)과 역할 출력 계약 v2(근거 번호 인용·역할 항목 격리)·추출 누락 unit 격리를 더한다. **runner 이미지를 다시 빌드해야 한다**(새 schema 파일 `/app/card-role-v2.json`·contract `card-role-v2`), web·`analysis-worker`·프런트도 새로 올린다(판정 보기 `role_isolations` 가산). 순서는 v8 → v9와 같다: 이미지 재빌드 → v10 import(행 canonical sha = 파일 sha `8b5be91e…93f9`) → 선택 env·`BIDOPS_RL_ANALYSIS_POLICY_PATH`를 v10으로 → v9 승인 철회·`--policy analysis-policy-luna-rl-v10` 재승인 → mock 경로(T11) 확인. 각 단계는 직전에 사람 확인을 받는다.

**v10 → v11 전환(결정 C20).** 새 실행은 v11이 v10을 대신한다(파일 sha `8dabbbb4…f45a`; v10 행·attempt는 그대로이고 v10 → v11은 종합만 다시 실행의 계보가 아니다). 순서는 v9 → v10과 같고 runner 이미지 재빌드가 필요하다(새 schema `/app/card-role-v3.json`·`/app/card-synthesis-v3.json`). 각 단계는 직전에 사람 확인을 받는다.

(경로는 web 이미지 안 위치다. import에서 품질 합격을 지정하지 않는다. RL-05 실제 측정 결과는 인수 reject이며 C-2 품질 활성화와 별개다.) `policy_sha256`은 이 **행의 canonical sha**이고 파일 raw sha가 아니다. 값을 하나라도 바꾸려면 새 버전 파일을 발행하고 다시 import·승인한다.

**3. 전송 정책 승인(사람 직전 확인 대상, 실제 전송 권한을 여는 단계).**

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli approve-transfer-policy \
  --policy analysis-policy-luna-rl-v9 --actor '<담당자 이름>' --daily-cap <N> [--dry-run]
# v1~v8 행을 계속 쓰는 환경이면 --policy analysis-policy-luna-rl-v1|…|v8(정책 파일 경로도 같은 버전)
```

- 출력 JSON의 `approval_id`·`policy_sha256`·`daily_cap`·`created`·`errors`를 기록에 적는다. `--daily-cap`은 하루(KST)에 **실제로 외부 전송한** RL attempt 수의 **코드로 강제되는 상한**이다(1..50, 기본 10, 결정 B17). `today_used`는 `analysis.transfer.sent` 감사가 있고 mock이 아닌 attempt만 센다 — mock attempt·전송 전에 멈춘 attempt는 세지 않는다. 대신 시작(자동·수동·drain) 시점에는 아직 전송하지 않은 실제 attempt(queued·running)를 예약으로 함께 세고, worker가 첫 호출 직전에 상한을 다시 검사해 넘으면 `daily_cap_reached`로 실패시킨다(전송 0). 배치 B 격리 실증은 `--daily-cap 2`(실제 1건 + 재시도 1)로 고정했다. 활성 승인은 정책 sha당 하나이며 두 번째는 `active_approval_exists`(exit 2), 정책·선택 행·모델 identity가 어긋나면 `policy_identity_mismatch`(exit 2)다. `--dry-run`은 쓰기 없이 검사한다.
- 확인: `GET /api/analysis/transfer-policy`의 `active.approval_id`·`daily_cap`·`today_used`가 CLI 출력과 같은지 본다(화면 조작은 서버 상태로 확인한다).
- **철회:** `revoke-transfer-policy --approval-id <id> --actor <이름> --reason <사유>`. 한 번만 가능하며 이후 자동 경로와 worker가 호출 전에 `policy_not_approved`로 멈춘다. 이미 실행 중인 attempt도 첫 호출 전 승인 재검사에서 멈춘다. 상한을 바꾸려면 철회하고 새로 승인한다.

**4. Luna runner와 인증·egress.** 기존 `docker-compose.luna.yml`(profile `luna`)을 쓴다. `codex-runner`만 `luna-internal`(내부)과 `luna-egress` 두 네트워크에 있고 web·`analysis-worker`는 내부망뿐이며 runner에는 DB·MinIO·원문 volume이 없다. 인증은 `env/luna.env`의 `BIDOPS_CODEX_AUTH_FILE`이 가리키는 `auth.json` 파일 **하나를 compose secret으로 runner에만 읽기 전용 마운트**한다. 로컬 PoC는 호스트 개인 로그인 파일을 쓰며(2026-10-17 인터뷰 D6, CLI 0.162.1) 값·파일 내용을 로그·문서·채팅·명령줄에 남기지 않고 다른 서비스에 마운트하지 않는다. runner 이미지는 `card-extract-v1|card-role-v1|card-synthesis-v1` contract를 알아야 하므로 이 변경 뒤 다시 빌드한다. `luna-egress`는 host allowlist가 아니므로 운영에서는 방화벽에서 runner의 필요한 통신만 허용했는지 따로 확인한다. 구현·mock 검증은 Luna 인증·모델 접근·실자료 품질을 증명하지 않는다. 오케스트레이션 명령 배열과 롤백은 [Luna 운영 적용 절차](../0922_luna-deep-review/apply.md)의 compose 조합을 따르고 서비스 교체는 `up -d --no-deps --no-build --force-recreate`로 한다.

**4a. 로컬 원본 연결(결정 B15, 첨부 행에 파일이 없을 때).** G2B 링크만 있고 바이트가 없는 사전규격 첨부 행에, 이전 수집본과 sha256이 같은 로컬 원본을 연결한다. G2B를 부르지 않으며 바이트는 G2B fetcher와 **같은** 격리→ClamAV·MIME/확장자 검사→source→문서·구조 경로를 지난다. 연결 뒤 그 공고의 문서 준비를 trigger `operator_local_original`로 연다(등급·브리핑 자격만 건너뛰고 취득 종결·safe·구조·확정 fence는 그대로). 첨부 worker와 같은 자격·네트워크(worker DB 자격, `scanning` 네트워크의 ClamAV, 문서 storage, 변환 scratch)를 쓰므로 `prespec-attachment-worker` 컨테이너에서 실행하고, HWP 변환을 위해 `document-worker`가 떠 있어야 한다. 운영 DB 쓰기이므로 직전에 사람 확인을 받는다.

```bash
# 파일을 컨테이너 안의 임시 경로로 복사한다(호스트 경로는 컨테이너에서 보이지 않는다).
docker compose -f docker-compose.yml cp '<로컬 원본.hwp>' prespec-attachment-worker:/tmp/local-original.hwp
docker compose -f docker-compose.yml exec -T prespec-attachment-worker \
  python -m app.deep_review.cli attach-local-original \
  --notice-id <notice_id> --attachment-id <attachment_id> --file /tmp/local-original.hwp \
  --expected-sha256 <이전 수집본 sha256> --actor '<담당자 이름>' --dry-run
# dry-run 출력(errors=[])을 확인한 뒤 같은 명령을 --dry-run 없이 한 번 실행하고, 임시 파일을 지운다.
docker compose -f docker-compose.yml exec -T prespec-attachment-worker rm -f /tmp/local-original.hwp
```

- 출력 JSON `{notice_id, attachment_id, content_sha256, size_bytes, provenance, fetch_status_before, document_version_id, scan_status, preparation, dry_run, errors}`를 기록에 적는다. `preparation.confirmed=true`면 묶음이 `ready`다. `preparation.reason=awaiting_fetch`면 같은 공고의 다른 첨부 취득이 아직 끝나지 않았다는 뜻이며 그 첨부도 연결하거나 취득을 종결한 뒤 다시 준비한다.
- 거부(exit 2, 쓰기 없음): `sha256_mismatch`, `attachment_notice_mismatch`, `attachment_not_found`, `attachment_has_bytes`(문서가 이미 있거나 취득 `완료` — 이중 등록 방지), `attachment_fetch_in_progress`(G2B worker lease 중), `attachment_source_not_g2b`, `attachment_retired`, `notice_not_pre_spec`, `unsupported_extension`, `file_not_regular`(symlink·디렉터리 포함), `file_size_limit`(50MiB), `malware_detected`, `mime_mismatch`. 재시도성 실패(exit 1): `clamav_unavailable`·`converter_unavailable`·`service_unavailable`·`storage_failed`. 출력·stderr에 로컬 경로는 없다.
- 감사 `prespec_attachment.local_original`(actor=담당자, `provenance=operator_local_original`, sha·크기·문서 id·취득 행의 이전 상태)이 성공·검사 차단마다 하나 남는다. 성공하면 첨부의 취득 행(있으면)이 `완료`로 바뀌고 lease fence가 올라가 이후 G2B worker가 같은 첨부를 다시 쓰지 않는다. 문서 버전은 `source_kind=provider`·`source_system=g2b`(원래 첨부의 출처)이고 `created_by_name`이 담당자다.

**mock 전체 경로(T11, 결정 B16).** `BIDOPS_ANALYSIS_PROVIDER=mock`(참조 모드 필수)이면 카드 판정은 같은 단계·검증기를 지나되 결정적 mock client가 답한다(단위 원문을 그대로 인용, 제약·숫자 없음, 종합은 `판단 불가`). runner·네트워크 호출이 없고 `analysis.transfer.sent`도 남지 않으며 상한을 쓰지 않는다. 생성 감사의 provider 계보가 `mock-analysis`라 판정 보기의 `quality_status`는 `mock_reference`다 — 연결 증명일 뿐 품질 근거가 아니다. mock으로 판정한 공고의 review는 계보가 mock으로 고정되어 같은 DB에서 실제 호출로 이어 갈 수 없으므로(worker가 `service_unavailable`로 거부) T11과 T12는 서로 다른 DB에서 한다.

**5. 수동 요청 시운전.** 자동 시작은 끈 채(`BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`, 개요·심층 자동도 false) 사업기회 판정 탭의 "다시 판정"(또는 `POST /api/opportunities/{id}/verdict-requests`)으로 한 건만 요청한다. 직전에 사람이 대상 공고·상한·승인(`today_used`)을 확인한다. 실제로 전송한 요청만 상한을 소비하고(B17) `analysis.transfer.sent` 감사가 첫 호출 전에 한 번 남아야 한다 — **그 감사가 없는 전송, payload에 노트·`proposed`/`unknown` 값·운영 정보가 들어간 정황, 상한 초과는 즉시 중단하고 보고한다.** 검증 실패(`failed`·`needs_human_review`)는 자동으로 다시 시도하지 않으며 사람이 한 번 다시 판정할 수 있다. 같은 시도가 또 실패하면 멈추고 후속 의존 실행(RL-04 초안)은 보류한다. 증거는 [README](../validation-runs/2026-10-17-rl/RL-03/README.md)에 attempt id·sha·호출 수·시간·`analysis.transfer.sent` 건수로 남긴다.

**6. 자동 시작과 큐(운영 자동화, 별도 확인).** `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=true`는 `build-briefing`이 만든 추천 항목마다 위 자동 시작 조건을 평가하게 만든다. 추천받은 SW=Y 사전규격에 ready 묶음이 없으면 문서 준비를 열며, 이때 묶음 생성의 등급 자격만 건너뛴다(결정 B18, 개요 플래그와 무관; 안전 검사·확정 fence는 그대로). 이 플래그를 켜는 것, cron(브리핑 CLI)에서 켜진 채 도는 것은 실제 모델 전송을 일으키므로 승인 상한과 직전 확인이 필요하다. 상한을 넘은 요청은 큐에 쌓이고 **다음 브리핑이 새로 만들어진 직후** 한 번 처리된다(자동 따라잡기 없음). 필요하면 수동으로:

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli drain-verdict-queue [--date YYYY-MM-DD]
# RL-05 홀드아웃: 자동 분석에서 뺄 사전규격
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli drain-verdict-queue --hold <notice_id,…> --reason gold_holdout --actor '<이름>'
```

`drain`의 `--date`는 "그 날짜(KST) **이전**에 쌓인 요청"을 처리하라는 뜻이며 한 번만 돈다. 출력의 `stopped_reason`(`daily_cap_reached`·`policy_not_approved`·`auto_start_disabled`)·`remaining`(남은 큐)을 확인한다. 큐 길이가 늘기만 하면 상한이나 승인을 사람이 다시 정한다. 자동 시작의 실제 스택 증명은 T11 mock이 하며(실제 스택에서 자동 시작을 켜 둔 실증은 이 기능의 범위가 아니다) 가짜로 증명되지 않는 생성→폴링→후속 경로는 실제 스택에서 한 번 돌기 전까지 "검증됨"이라 쓰지 않는다.

**7. Slack 스레드 답글은 지금 켜지 않는다(D5).** 판정 완료 스레드 답글은 판정을 닫는 `analysis-worker`가 `core/slack.py`로 보내는데, Slack overlay(`docker-compose.slack-egress.yml`)는 `env/slack.env`와 egress network를 `web`·`slack-worker`에만 주고 `analysis-worker`에는 주지 않는다. 그래서 현재 구성에서는 전송기 호출 전 검사가 막아 답글이 **건너뛰어지며 오류가 아니다**. 켜려면 worker에 토큰·egress를 주는 별도 overlay 변경과 사람 확인이 필요하며 이번 범위에서는 하지 않았다. 스레드 답글의 증명은 가짜 서버 검사까지이고 실제 Slack 게시 증명으로 적지 않는다.

**8. 되돌리기.** 가장 빠른 차단은 `revoke-transfer-policy`(이후 호출 0)이고, 그다음 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`·`BIDOPS_RL_ANALYSIS_ENABLED=false`로 재생성한다. 이미 저장된 판정·단계 행은 append-only라 지우지 않는다. 승인 철회는 감사 기록이 남는 CLI로만 하며 SQL로 고치지 않는다.

**검증 명령(문서 단계 근거).** 변경 영향 범위만 돌린다: `pytest tests/deep_review/test_card_analysis.py tests/deep_review/test_card_compare.py tests/app/test_transfer_policy.py tests/app/test_verdict_api.py tests/app/test_verdict_payload_guard.py tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py`, PostgreSQL 변형은 일회용 `postgres:17.11`과 `BIDOPS_TEST_POSTGRES_URL`로 `test_card_analysis_postgres.py test_verdict_trigger_postgres.py test_db_migrations.py test_runtime_database_privileges.py`, 화면은 `npx playwright test --project=app verdict.spec.ts opportunity-record.spec.ts`.

## RL 제안서 초안 운영 (RL-04, 2026-10-18)

판정이 끝난 사업기회의 제안서 초안(여섯 절·요구사항 대응표·PDF)을 만드는 실행·설정·승인 절차다(규칙은 [business-rules.md "제안서 초안"](../business-rules.md#제안서-초안-rl-04-2026-10-18), 계약은 [contracts.md "제안서 초안"](../contracts/rl.md#제안서-초안-rl-04-2026-10-18)). 구현·mock 및 실제 모델 검증은 `bidops-local` 격리 스택에서 수행했다. 코드는 2026-10-19 운영에 배포됐으나 RL 분석은 비활성이다. 실제 Luna 초안 1건(T11)은 후속 실행에서 `partial`(4/6절 완료)이며 실적·운영 절은 참조 검증에 실패했다. [RL-04 실행 기록](../validation-runs/2026-10-17-rl/RL-04/README.md)이 최종 근거다. 실제 초안·정책 승인·재배포·migration은 모두 직전에 사람 확인을 받는다.

**설정.**

| 키 | 기본 | 역할 |
|---|---|---|
| `BIDOPS_PROPOSAL_POLICY_PATH` | `policies/proposal-policy-luna-v1.json` | import 원본(immutable). 승인 CLI가 이 파일의 identity·sha를 선택 행과 대조한다 |
| `BIDOPS_PROPOSAL_POLICY_VERSION_ID` | 없음 | import한 정책 행 선택. 비면 초안 생성·worker가 fail closed(`analysis_policy_unavailable`). RL-03 선택 env와 별개 |
| `BIDOPS_PDF_FONT_DIR` | `/usr/share/fonts/truetype/nanum` | 백엔드 이미지가 apt `fonts-nanum`으로 넣는 `NanumGothic.ttf`·`NanumGothicBold.ttf`의 위치. 저장소에는 폰트 파일이 없다(D9). 없거나 읽을 수 없으면 내보내기가 503 `pdf_unavailable`. 이미지 폰트가 바뀌면 `font_sha256`이 바뀌어 같은 초안도 새 PDF가 된다 |
| `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`BIDOPS_PROPOSAL_PDF_SECRET_KEY` | 없음(compose는 `:?`로 요구) | 버킷 `bidops-proposal-pdf` 전용 자격증명. **web과 minio-init만** 받는다(분석 worker는 PDF를 다루지 않는다, 결정 B49) |
| `BIDOPS_RL_ANALYSIS_ENABLED`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED`·`BIDOPS_REFERENCE_WORKFLOW_MODE` | 기존 | 셋 다 켜져 있어야 경로가 열리고 실행된다. 꺼져 있으면 제안서 경로는 404·503이다 |

RL 키와 정책 선택 env는 web과 `analysis-worker`가 **같은 값**으로 읽어야 하므로 env 파일·overlay로 주고, 올린 뒤 서비스마다 `docker compose exec -T <서비스> printenv BIDOPS_PROPOSAL_POLICY_VERSION_ID`로 확인한다. PDF 키는 web에서만 확인한다.

**1. 배포 전제(운영 변경, 직전 사람 확인).** migration `0041_proposal_draft`(테이블 4개, [contracts.md](../contracts/rl.md#제안서-초안-rl-04-2026-10-18))와 `scripts/runtime-privileges.sql`의 새 권한을 적용하고 `web`·`analysis-worker`·`codex-runner`(contract `proposal-section-v1` 스키마 COPY) 이미지를 새로 올린다. 전체 백업과 `before-rl-proposal-<날짜>` 롤백 태그를 먼저 남긴다. **main 병합 뒤 운영 스택을 다시 올리기 전에** 운영 env(`.env` 등 gitignore 파일)에 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`를 넣고 `minio-init`을 다시 실행해 버킷 `bidops-proposal-pdf`(versioning·전용 정책·365일 만료)를 만든다 — 키가 없으면 compose가 web·minio-init 기동을 거부한다(결정 B49). 이 단계도 직전에 사람 확인을 받는다.

**2. 정책 import와 선택.** 파일을 고쳐 쓰지 않고 immutable 파일을 import한다.

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli import-profile-policy \
  --policy /app/web/backend/app/deep_review/policies/proposal-policy-luna-v1.json \
  --label proposal-policy-luna-v1 \
  --expected-policy-sha256 0eb36cf9e4318e447dd2c66f59a060a9ec1d87b92c23326200867060973e7d91 --actor '<담당자 이름>'
# 출력의 policy_version_id를 BIDOPS_PROPOSAL_POLICY_VERSION_ID로 env에 넣고 web·analysis-worker를 재생성한다.
```

이 행은 전역 active policy나 RL-03 판정 정책으로 쓸 수 없다(선택하면 fail closed).

**3. 전송 정책 승인(사람 직전 확인, 실제 전송 권한을 여는 단계).**

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli approve-transfer-policy \
  --policy proposal-policy-luna-v1 --actor '<담당자 이름>' --daily-cap 1 [--dry-run]
```

- 실제 사용(T11)은 `--daily-cap 1`(초안 1건 = 절 6건, 배치 B 인터뷰 D3·D10)이다. 기본은 3, 범위 1..20이며 절 다시 쓰기는 1/6건으로 센다. 승인 행은 `scope={"purposes":["proposal"]}`로 RL-03 승인과 따로 있고 서로의 게이트·상한에 보이지 않는다. 출력 JSON의 `approval_id`·`policy_sha256`·`daily_cap`을 기록한다.
- 철회는 `revoke-transfer-policy --approval-id <id> --actor <이름> --reason <사유>`이고 이후 worker가 첫 호출 전에 `policy_not_approved`로 멈춘다(절은 `failed`). 상한을 바꾸려면 철회하고 새로 승인한다.

**4. 실행.** 초안은 사업기회 제안서 탭의 "제안서 초안 만들기"(또는 `POST /api/opportunities/{id}/proposal-requests`)로 만든다. 직전에 사람이 대상 판정·상한·승인을 확인한다. 절 실행은 합성 `analysis-worker`의 같은 슬롯에서 **다른 큐가 비었을 때 마지막으로** 돈다(새 서비스 없음). worker는 절마다 입력을 동결·검사한 뒤 승인·상한을 다시 보고(자기 절 제외) → runner 주소를 검사하고 → `analysis.transfer.sent`(purpose `proposal`)를 한 번 남긴 뒤 → `codex-runner`(`proposal-section-v1`, 절당 900초)를 부른다(주소·승인 실패는 감사·상한 소비 없이 절 `failed`). Luna runner·인증·egress는 RL-03과 같다("RL 카드 판정 운영" 4). 실패한 절은 자동으로 다시 돌지 않으며 사람이 "이 절 다시 쓰기"를 누른다(검토 완료·제출 준비 단계에서는 막히고 새 초안으로 다시 만든다, 결정 B50). 초안 1회차의 절들은 첫 실행부터 5400초를 공유한다.

**5. mock 경로(T10).** `BIDOPS_ANALYSIS_PROVIDER=mock`(참조 모드 필수)이면 같은 게이트·검증기를 지나되 결정적 mock client가 절을 만든다(요구사항 원문을 통째로 인용, 빠진 회사 사실은 빈 자리, 대응표 누락 0). runner·네트워크 호출이 없고 `analysis.transfer.sent`도 없다. 생성할 때는 실제와 같이 **활성 proposal 승인과 상한 여유가 필요하지만** mock 계보 초안의 절은 사용량에 세지 않는다. 생성 감사의 provider 계보가 `mock-analysis`로 고정되어 결과는 `mock_reference`이고, 나중에 실제 provider worker가 그 초안을 실행하지 않는다(`model_binding_invalid`). mock 초안을 실제 품질 근거로 쓰지 않는다. 격리 스택 시운전 기록은 RL-04 검증 기록에 있다.

**6. PDF.** "PDF로 내보내기"(`POST /api/proposals/{draft_id}/exports`)는 web이 렌더해 `bidops-proposal-pdf`에 암호화 없이 저장하고 같은 내용이면 기존 PDF를 돌려준다. 저장 바이트는 `content_object.sha256`과 같아야만 내려가며(`GET …/exports/{id}.pdf`), 이 버킷은 객체 백업·복구·active hash 검증 대상이고 365일 뒤 만료한다. 폰트가 없는 환경(호스트 테스트 등)은 `BIDOPS_PDF_FONT_DIR`로 위치를 준다.

**7. 되돌리기.** 가장 빠른 차단은 `revoke-transfer-policy`(이후 호출 0), 그다음 `BIDOPS_RL_ANALYSIS_ENABLED=false`로 재생성이다. 초안·절·수정·PDF 행은 append-only라 지우지 않으며 SQL로 고치지 않는다.

**검증 명령(문서 단계 근거).** `pytest tests/deep_review/test_proposal_input.py tests/deep_review/test_proposal_validation.py tests/deep_review/test_mock_proposal_client.py tests/deep_review/test_proposal_render.py tests/app/test_proposal_transfer_policy.py tests/app/test_proposal_draft.py tests/app/test_proposal_api.py tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py tests/app/test_runtime_contract.py`(PostgreSQL 변형은 `BIDOPS_TEST_POSTGRES_URL`, PDF 사례는 `BIDOPS_PDF_FONT_DIR`이 있어야 skip 없이 돈다).

## RL 판정 gold 인수 평가 (RL-05, 2026-10-19)

RL-03 카드 판정이 사용자 gold 10건과 맞는지 보는 평가 절차다(기준·독립성 규칙은 [model-quality-gate.md "RL 판정 gold 인수"](../model-quality-gate.md#rl-판정-gold-인수-rl-05), 계약은 [RL-05 spec](../work/groups/RL/features/RL-05-gold-acceptance/spec.md)). **격리 스택 `bidops-local`의 별도 DB에서만 하고 운영 `bidops` 스택·운영 DB는 건드리지 않는다.** 제품 CLI `export-evaluation`은 읽기 전용이고 채점·인수는 제품 밖(`scripts/rl-gold.py`)과 사람이 한다. 결과는 사람이 `accept`하기 전까지 `unmeasured_reference`이며 품질 근거가 아니다. 실행 기록은 [validation-runs/2026-10-19-rl/RL-05](../validation-runs/2026-10-19-rl/RL-05/README.md)다.

**평가 디렉터리.** Git 밖 `.sdlc/local-runtime/rl-evaluation-<날짜>/`(`.git/info/exclude`로 무시)에 `selection.v1.json`, `cards/`, `cards.json`, `gold.v1.json`, `actual.v1.json`, `alignment.v1.json`, `prediction.v1.json`, `receipt.json`, `score.v1.json`, `acceptance.json`을 둔다. `--out`으로 쓰는 **파일은 모두 새로 만든다**(같은 이름이 있으면 `output_exists`, 디렉터리는 이미 있어도 된다)이고 worktree 안이면 git이 무시하는 경로만 허용한다(`output_not_ignored`). `export-evaluation`은 DB·객체 저장소에 닿는 컨테이너 안에서 돌고 `--selection`·`--gold`·`--out`은 그 컨테이너 안 경로이므로 평가 디렉터리를 마운트하거나 결과를 꺼내 쓴다. `rl-gold.py`는 파일만 읽고 쓰며 호스트에서 돈다. 문서 원문·gold·모델 답은 저장소·로그에 남기지 않는다.

1. **후보 고르기.** 사전규격 중 문서 준비 `ready`, 개요 `completed`, **묶음마다 분석 원문(source)이 하나**인 것만 후보다. 원문이 여럿인 묶음은 export가 `selection_mismatch`로 거부한다. 요구사항 카드가 10개 미만인 문서는 카드 상태 표본 10개를 채울 수 없어 gold를 쓸 수 없으므로 뺀다(카드 수는 5단계 `cards.json`에서 보이므로 후보 몇 건을 여유로 두고 고른다). 선정은 사람이 하며 도구는 고르지 않는다. 대체 후보까지 4단계의 홀드아웃에 함께 넣는다.
2. **회차 적재.** 격리 DB에 수집 회차 디렉터리를 바이트 그대로 복사하고(파일별 sha256 대조) 적재한다: `python -m app.lifecycle.ingest.cli --run <회차> --collection`. 격리 DB에는 사업기회 연결 대상·선별 결과가 없어 `opportunity_link_target_missing`·`screening_results_missing` 경고가 나는 것이 정상이다. 적재 직후 `GET /api/runs/<회차>/warnings`로 경고 종류만 확인한다.
3. **원문 연결.** 격리 DB에는 G2B 링크만 있고 바이트가 없다. 검증된 객체 백업(`object-versions.tsv`의 sha256과 버전이 맞는 source 객체)이나 담당자가 가진 사본을 가져와 [RL-03 4a절](#rl-카드-판정-운영-rl-03-2026-10-17)의 `attach-local-original --notice-id <id> --attachment-id <id> --file <파일> --expected-sha256 <sha256> --actor '<이름>'`로 연결한다. **`--dry-run`을 먼저** 보고(`errors=[]`) 실제 실행한다. G2B를 부르지 않으며 ClamAV·MIME 검사를 지난다. 모든 묶음이 `ready`인지 확인한다.
4. **홀드아웃 — 다른 무엇보다 먼저.** 선정 공고를 gold 작성 전에 자동 분석에서 뺀다: `python -m app.deep_review.cli drain-verdict-queue --hold <notice_id,…> --reason gold_holdout --actor '<이름>'`(RL-03 6절). 공고마다 `verdict_request`에 `rejected`·`gold_holdout` 행이 생기고 같은 시점에 그 공고의 RL review가 0건이어야 한다. 선정이 끝날 때까지 web·worker의 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`를 유지한다.
5. **카드 pack과 빈 gold 양식.** 사람이 `selection.v1.json`(`bidops.rl-evaluation-selection.v1`: 문서별 `document_id`·`notice_id`·`opportunity_id`·`source_sha256`·`structure_id`·`manifest_id`·`title`·`agency`, `company_sha256`=활성 graph sha, `ontology_sha256`, `selected_on`)을 쓴다. 이어서:

   ```bash
   python -m app.deep_review.cli export-evaluation --cards --selection <eval>/selection.v1.json --out <eval>/cards
   python3 scripts/rl-gold.py export-cards --cards-pack <eval>/cards --out <eval>/cards.json
   python3 scripts/rl-gold.py blank-gold --cards <eval>/cards.json --selection <eval>/selection.v1.json --out <eval>/gold.v1.json
   python3 scripts/rl-gold.py gold-check --gold <eval>/gold.v1.json --selection <eval>/selection.v1.json   # 빈 양식은 human_gold_incomplete(exit 2)가 정상
   ```

   `selection_mismatch`·`binding_mismatch`는 선정 파일이 DB와 다르다는 뜻이다. 카드 pack은 읽기 전용으로 꺼낸 구조·page map이고 모델 답이 없다. PDF 스냅샷이 없으면 page map 파일이 없고 `page_map_sha256`은 `null`이다.
6. **사람이 gold를 쓴다 — 모델 실행 전.** 문서마다 판정·차단 조건·충족/부족·주의·카드 상태 표본 10을 적고 `annotator`·`authored_at`(ISO-8601, 시간대 포함)·`written_before_model_output=true`를 채운다. 미작성 `null`과 확인 후 없음 `[]`을 구분한다. `gold-check`가 exit 0이어야 다음으로 간다. gold를 고치면 새 버전 디렉터리를 만든다.
7. **실제 판정(모델 실행).** `gold-check` 통과 뒤에만 공고마다 수동으로 요청한다(`POST /api/opportunities/{id}/verdict-requests` 또는 판정 탭). 이 요청이 holdout 행을 해제한다. **실제 Luna 전송은 RL-03 정책 단위 승인([RL-03 3절](#rl-카드-판정-운영-rl-03-2026-10-17), 상한)이 있어야 하고 요청 직전에 사람이 대상·상한·승인을 확인한다.** 상한을 넘는 날은 다음 KST 날로 나눈다. 판정이 `failed`면 그대로 두고 결정 B55의 종합 재실행 같은 RL-03 절차로 이어 가며 gold·표본을 바꿔 맞추지 않는다. 완료된 attempt만 채점 대상이다.
8. **actual → alignment → 최종 export → 채점.** 순서가 바뀌면 안 된다.
   1. 먼저 gold·alignment **없이** 별도 초안 디렉터리로 내보낸다: `export-evaluation --actual --selection <eval>/selection.v1.json --out <eval>/actual-draft`. 결과는 `actual.v1.json` 하나(모델이 낸 차단 조건 단위 목록 포함)다. 선정 공고마다 완료된 RL attempt가 없으면 `missing_attempt`, 같은 조건의 정책 다름·mock·실패·실행 중 attempt는 점수 대상이 아니라 건수만 요약에 남는다.
   2. 사람이 `alignment.v1.json`(`bidops.rl-condition-alignment.v1`)을 쓴다: **gold 파일 sha256과 위 actual 파일 sha256을 적고**, 모델의 차단 조건 단위마다 대응하는 gold 조건 ID(없으면 빈 목록)와 사유를 적는다. 모델 차단 단위는 하나도 빠지면 안 된다(`invalid_alignment`).
   3. 최종 디렉터리(**초안과 다른 경로** — 같은 이름 파일을 다시 만들 수 없다)로 내보낸다: `export-evaluation --actual --selection … --gold <eval>/gold.v1.json --condition-alignment <eval>/alignment.v1.json --out <eval>`. `gold_after_model`·`holdout_violated`면 export가 거부되고 그 표본은 교체 대상이다. 성공하면 `actual.v1.json`·`prediction.v1.json`·`receipt.json`이 생긴다. 초안과 최종의 `actual.v1.json`은 같은 바이트(같은 attempt·같은 입력)라 alignment의 actual sha가 그대로 맞는다.
   4. `python3 scripts/rl-gold.py score --gold <eval>/gold.v1.json --prediction <eval>/prediction.v1.json --criteria docs/work/groups/HP/preparation/acceptance-criteria.approved.v1.json --out <eval>/score.v1.json`. 출력은 지표 네 개·비일치 목록이고 `decision=null`이다.
9. **인수 기록(사람).** 사람이 `acceptance.json`(`bidops.rl-acceptance.v1`)에 `decision`(`accept|reject|defer`)·`decided_by`·`decided_at`·`reason`을 적는다. 같은 파일에 `criteria_sha256`·`selection_sha256`·`gold_sha256`·`actual_sha256`·`alignment_sha256`·`prediction_sha256`·`scoring_tool_sha256`·`scoring_input_sha256`(receipt + criteria sha + 도구 sha의 canonical sha, [HP-06](../work/groups/HP/features/HP-06-gold-acceptance/spec.md) 정의)·`metrics`·`adjudication_file_sha256`(비일치·중대 오류 검토 파일)를 채운다. 도구는 이 파일을 쓰지 않는다. 파일 sha256을 검증 기록에 적는다.

**되돌리기·한계.** export는 쓰기가 없어 되돌릴 것이 없다. 홀드아웃·gold·alignment를 잘못 만들면 새 평가 디렉터리와 새 버전으로 다시 한다(옛 것은 남긴다). 홀드아웃 행은 제품 REST·CLI로만 바꾸고 SQL로 고치지 않는다. 표본 10건·한 회사·참조 실행이므로 통과해도 운영 품질 보증이 아니다.
