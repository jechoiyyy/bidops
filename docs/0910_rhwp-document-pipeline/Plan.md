# rhwp 문서 변환 파이프라인 진행 계획

작업명: rhwp-document-pipeline · 기준일: 2026-09-11 · 상태: 승인된 운영 배포·6건 source-only 재준비·Qwen 참조 실행 4건 사람 검토 대기

이 문서는 새 세션이 다른 맥락 없이 이 작업을 이어갈 수 있도록 순서·담당·게이트·현재 상태·재현 명령을 모아 둔다. 내용이 이미 다른 문서에 있으면 여기 다시 적지 않고 링크한다. 단계가 끝나거나 결정이 바뀌면 §7 진행 기록에 덧붙이고, 결정 자체는 [ADR.md](ADR.md)에 적는다.

## 현재 MVP 상태 (2026-09-11)

- 현재 DB/runtime head는 `0025_overview_claim_ledger`다. 이번 MVP 보완은 기존 nullable
  snapshot/target/sidecar 구조 안에서 구현했으며 새 migration은 없다.
- native core(PDF·전체 페이지 텍스트·대응표·renderer/source 결속)를 먼저 검증하고 보조
  digest를 나중에 처리한다. 현재 producer는 `bidops.section-candidates.v2`이고
  `outline|clause|page`, 전체/반환 개수와 부분 목록 경고를 구분한다. unavailable 경고와
  함께인 null 후보 sidecar/참조만 허용하고 경고 없는 누락·존재 후보 무결성 실패는
  차단한다. v1은 과거 read 호환이다.
- 일부 공백 쪽은 text와 source/selected hash를 그대로 보존하되 전체 공백 입력은 호출
  전, 공백 quote 근거는 초안 후 결정적 검증에서 거부한다. 같은 줄 복수 장 제목은
  `ambiguous_scope_boundary`로 사람에게 보낸다.
- 범위 조회 v2와 안전한 target PDF로 후보 유무와 관계없이 직접 쪽을 고를 수 있다. 부분 후보의
  index/assist는 차단하며 확정은 새 target만 추가한다. 옛 결과는 이력으로 보존하고 current와
  회사 핏에서는 `stale/target_superseded`로 제외한다.
- policy v5는 실제 두 단계 structured request 전체, 확인된 context, 출력·chat 예약을 매 호출
  전에 검사한다. 용량 실패는 `failed/input_capacity_exceeded` 기술적 미실행이며 내용 검증 실패와
  다르다. 09:08~09:13 KST 승인된 Qwen 참조 실행은 초안 4회에 응답했지만 결정적
  검증 후 4건 모두 `needs_human_review`로 종결했고 의미 호출·형식 재생성·최종 개요·내용 통과는 0건이다.

| 0910 고정 대상 | 건수 | 현재 상태 |
|---|---:|---|
| 744·749·759·761 | 4 | 입력 준비 후 Qwen 초안 각 1회 응답. 모두 `needs_human_review`, 최종 개요·내용 통과 0 |
| 743·745·746·747·754·755 | 6 | source-only 재준비 완료. 743·745 outline 5/5, 746 page 67/50 partial, 747 page 111/50 partial, 754 outline 28/28, 755 outline 1/1. 모두 수동 범위로 분류 |
| 751·753·756·758·760 | 5 | 기존 사람 직접 쪽 범위 확인 필요 |
| 748·750·752·757 | 4 | 문서 선택/안전 차단 유지 |

위 표의 준비 분류는 입력 준비 4건, 수동 범위 11건, 문서·안전
4건이다. 754·755는 처음 자동 ready였지만 선택 제목이 `제안개요` 작성 양식이라 입력 준비에서
제외했다. 안전 PDF는 15건을 유지한다. source-only activation ON/OFF와 모델 실행 0건은
09:08 전 이력이다. 이번 실행은 재수집·재변환 0건으로 C-1/C-2 입력을 재사용했고,
`qwen3.8-27B` revision `5fa804ff0ecc0de9167f8b63127c42e1d421a9451662922ace8622d0b01b824e`와
context 262,144를 확인했다. 정책·payload·호출 상한은 바꾸지 않았다.

운영 재준비 사실: 최초 이미지 `bidops-prespec-mvp:20260911`
(`90c9794f7e6314394dfd35d892840bf854628d2dc86b14ab50b8d28d9de19f1e`)로 08:02~08:03 KST
web·document-worker 두 개를 교체했고 env/network/mount/UID/resource와 head 0025를 유지했다.
08:04:11~08:06:29 KST에 위 6건을 기존 source로 각 1회 준비했다. 모든 건의 exact
source/PDF/page-text version·hash와 최신 clean을 확인했고 신규 snapshot 6, target 6,
object/location 각 34개만 append했다. 기존 snapshot/target/attempt/개요/리뷰/document/object/
location 행의 전후 MD5는 동일했다. 이어 `제안개요` 오선택을
`ambiguous_scope_boundary`로 보내는 최소 selector 가드를 추가한
중간 이미지 `bidops-prespec-mvp:20260911-scope`를 거쳐 optional 후보 scratch/cache
경계까지 반영한 최종 이미지 `bidops-prespec-mvp:20260911-advisory-final`
(`sha256:223019128c101ea131d855256c950d06f0edda393281556656c1cea1e4c72d9f`)를 08:28:50~08:28:52 KST
document-worker 두 개와 web에 반영했다. image 외 env/network/mount/user/resource·pids·memory는
같고 web은 healthy, DB/runtime head는 0025다. 배포된 document protocol·native artifacts·v4 코드
SHA는 로컬과 일치했다. 앞서 scope 이미지에서 확인한 754·755의 실제 v2 API는 200이며 저장 ready target과 선택
쪽을 바꾸지 않은 채 `ambiguous_scope_boundary`, `can_confirm=true`를 반환한다. 두 target PDF도
200, exact SHA, private no-store·nosniff·CSP sandbox를 확인했고 마지막 scratch 보완 뒤에는 반복하지 않았다. optional/거부/roundtrip
고유 scratch 사례 8건과 기존 selector·조회 4건이 통과했다. 이 보정 배포에서
추가 변환·target 생성·모델 실행은 0이고 OFF 감사 `fe91c298-aceb-47b2-95e9-7560edc04be1`을 유지했다.

이후 사용자가 추가 sudo chain 조회를 생략하고 현재 기능 실행을 승인해 model activation
`11ada018-0546-4ab1-aece-15678343f6d0`으로 744·749·759·761을 실행했다. attempt 4,
verification 4, draft dispatch/response event 8, model response object 4건만 추가됐고 result는 0건이며,
기존 10개 테이블의 기존 행 MD5는 전후 같다. 4개 v2 API와 `needs_human_review` attempt PDF는
모두 200이고 exact hash를 확인했으며 이번에 브라우저 실화면은 다시 실행하지 않았다.
OFF 감사 `a6e96d1b-9c8a-40b6-87f7-d1e177c21222`로 종료해 active attempt 0건이다. 기존 방화벽은
변경하지 않았고 원문·검증·정책·호출 상한을 풀지 않았다. 결과는
`unmeasured_reference`로서 운영 품질·정책 활성화 승인이 아니며, 근거는
[실행 요약](../../.dryforge/prespec-qwen-0911-mHF0bO/README.md)과 그 폴더의 안전 metadata JSON이다.

문서 동기화는 Sol medium이 이 폴더의 ADR·Requirements·Design·Spec·Plan을 맡아 완료했고,
관리자가 최종 diff와 실행 증거를 대조했다. 남은 용량 계산식·검증 시점·과거/현재 표기만
문서에서 보정했다. 앱 검사나 운영 실행을 추가하지 않았으며 상세 실행·검증·미완료 항목은
[안정화 Plan](../0910_prespec-workflow-hardening/Plan.md)과
[이번 실행 기록](../../.dryforge/prespec-mvp-deploy-20260911-OIBy24/README.md)을 따른다.

## 0. 새 세션 시작 절차

1. 저장소 지침 [CLAUDE.md](../../CLAUDE.md)와 [docs/standards.md](../standards.md), [docs/engineering-notes.md](../engineering-notes.md), [web/backend/AGENTS.md](../../web/backend/AGENTS.md)를 읽는다.
2. 이 작업의 정본 다섯 문서를 순서대로 읽는다. [ADR.md](ADR.md) → [Requirements.md](Requirements.md) → [Design.md](Design.md) → [Spec.md](Spec.md) → 이 Plan이다.
3. 먼저 위 "현재 MVP 상태"와 이 문서 끝의 최신 진행 기록을 확인한다. R0~R7은 종료된 역사적 구현 단계이며 새 작업 체계로 재사용하지 않는다.
4. 현재 운영 상태는 [docs/tracking/status.md](../tracking/status.md) "사전규격 v4 최신 운영 상태"와 [docs/tracking/findings.md](../tracking/findings.md)의 notice 142 항목, [prespec-v4-implementation-plan.md](../tracking/prespec-v4-implementation-plan.md) "최신 운영 상태"에 있다.
5. 운영 명령(compose, 배포, v4 CLI, 참조 실행)은 [docs/operations.md](../operations.md)를 따른다. 특히 "사전규격 v4 준비" 절과 2026-09-10에 추가된 `--binding` 주석.

## 1. 진행 원칙

- 아래 R0~R7과 당시 브랜치·게이트는 역사 기록이다. 현재 계약은 ADR-RDP-009~011과
  [Spec §5~6](Spec.md#5-오류-코드)를 따르며 과거 단계명을 새 작업에 재사용하지 않는다.
- 구현·운영 완료 여부는 실제 diff, 제한된 검증, 운영 증거로 판단한다. 위임 보고만으로 완료를 추정하지 않는다.
- 검증은 변경 파일이 닿는 테스트만 돌린다([CLAUDE.md "검증 범위와 종료 기준"](../../CLAUDE.md)). 전체 backend·화면 스위트 각 1회는 2026-09-10 R5 최종 트리의 역사 기록이며 현재 재실행 지시가 아니다. 통과를 얻기 위한 반복 실행·검사 완화·재시도 루프를 넣지 않는다.
- 운영 상태 변경은 백업과 명시된 승인 범위 안에서만 한다. 이 후속은 web/document-worker
  배포와 실패 6건의 기존 source-only 재준비뿐이었다. 새 migration·모델 실행
  activation·모델 호출은 없었고 source-only activation ON/OFF 한 쌍은 실행했다.
- 기존 강제 게이트(원본 불변, unknown 보존, 자동 보정 금지, 외부 전송 금지, 참조 실행 표식 `unmeasured_reference`)를 그대로 지킨다([CLAUDE.md "강제 게이트"](../../CLAUDE.md)).
- 기능 구현을 최우선 목적으로 두고, 오버엔지니어링을 하지 않도록 유의한다.
- R2·R3는 사용자의 직접 작업 요청에 따라 위임 없이 진행한다. 격리 worktree는 Orca workspace 경로를 사용하고 실제 경로는 §7에 남긴다.

## 2. 역사적 상태 (2026-09-10 당시)

아래 표와 R0~R7 체크리스트는 당시 진행 사실이다. 위 "현재 MVP 상태" 및 현재 계약을 대체하지 않는다.


| 항목            | 상태                                                                                                                                                                                               | 확인 방법                                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| main | `1f66044`(R7 병합: `8b1c077` WP-A, `5a5646d` WP-B, `ae80dae` WP-C) 위에 R7 기록이 올라간다. 현재 SHA는 git log로 확인 | `git log --oneline -5` |
| 미병합 브랜치 | 없음. P1 WP-1~4·R0~R5는 모두 main에 있다(`git branch --list 'feat/*'`에 남은 이름은 병합 완료 브랜치) | `git branch --merged main` |
| 운영 컨테이너 | Compose 프로젝트 `bidops`. web `bidops-web-1`(이미지 `bidops-rdp-r7:20260910`, 127.0.0.1:18887), document-worker 2개(같은 이미지, pids 128·1 GiB·network none, 2026-09-10 R7 재생성). DB head `0024_section_candidates` | `docker ps`, `docker inspect <c> --format '{{.HostConfig.PidsLimit}}'`, `select version_num from bidops.alembic_version` |
| 배포 설정 보관      | `~/.local/state/bidops/deployments/<이름>-<id>/deploy.compose.json`                                                                                                                                | [operations.md "화면 노출과 edge overlay"](../operations.md)                                                              |
| v4 activation | OFF (마지막 감사 `5016643f-…`, 사유 `rdp_r6_native_snapshots_prepared_142_59_activation_restored_off`) | `select safe_metadata from bidops.audit_event where action='prespec_v4.activation' order by created_at desc limit 1` |
| notice 142 | native snapshot `f8a42b74-…`(`rhwp-svg-pdf`, 79쪽, 기존 구조 `22541eb7-…` 결속, 대응표 있음), target `f7c73503-…` ready(4~12쪽), attempt 없음. Canvas snapshot `e68670e0-…`·target `200e9557-…`은 보존. `current`는 여전히 실패 attempt `dbbc7b5f-…` | [R6 기록](../validation-runs/2026-09-10-rhwp-pipeline.md), [findings.md 142 항목](../tracking/findings.md) |
| notice 35/59 | 59는 native 경로 snapshot `3aa6c47f-…`(원본 PDF, 84쪽)·target `ec040093-…` ready. **35는 native 준비를 보류**: 새 구조 blocks 1,454 ≠ 기존 1,349라 `structure_binding_mismatch`가 나고 실패 attempt가 `current`를 덮으므로 실행하지 않았다. 둘 다 Luna 참조 결과 completed/current 보존 | [R6 기록](../validation-runs/2026-09-10-rhwp-pipeline.md), [status.md](../tracking/status.md) |
| 모델 endpoint   | overview vLLM `192.168.0.139:58765` 응답 없음(2026-09-09~10). `env/vllm.env`는 TEST-NET 자리표시자                                                                                                         | `curl -m 5 http://192.168.0.139:58765/v1/models`                                                                     |
| rhwp 호스트 빌드 | `/home/jechoi/projects/rhwp/target/release/rhwp` v0.8.6, 커밋 `cac9b4f7c`, SHA-256 `c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c`. R0에서 vendor에 등록됐고 R6 이미지에서 같은 hash 확인 | `sha256sum`, `git -C /home/jechoi/projects/rhwp describe --tags` |
| 표본            | 142 원본은 MinIO `source/7cc3b5f3894d984c-6f70b025586e46bdbe159ca4167a4e86.hwpx`(version `c11572d1-…`). HWP 2건은 `docs/design/(공고 2026-25) 제안요청서.hwp`·`과업지시서.hwp`(untracked, notice 10)              | Requirements §6                                                                                                      |
| 폰트 | R6 이미지에 Nanum 3종·Noto CJK·DejaVu와 `fontconfig`(`fc-list`). R5 이미지에는 `fc-list`가 없어 native 변환이 전부 `converter_unavailable`이었다(R6에서 보정). 폰트 manifest `92e5dc4f…1650a9` | `docker run --rm --entrypoint fc-list <image> : family` |


## 3. 자주 쓰는 명령

원본 꺼내기(web 컨테이너 안, 읽기 전용). heredoc을 쓸 때는 `docker exec -i`가 필요하다.

```bash
docker exec bidops-web-1 python -c "
from app.core.object_store import object_store
s = object_store(namespaces=('source',), read_namespaces=('source',))
data, meta = s.get('source', 'source/7cc3b5f3894d984c-6f70b025586e46bdbe159ca4167a4e86.hwpx', version_id='c11572d1-47e6-4f89-b2ab-91a35067643a')
open('/tmp/142.hwpx','wb').write(data)"
docker cp bidops-web-1:/tmp/142.hwpx ./142.hwpx && docker exec bidops-web-1 rm -f /tmp/142.hwpx
```

rhwp 호스트 실측(Spec §1과 같은 옵션):

```bash
cd /home/jechoi/projects/rhwp
R=./target/release/rhwp
$R export-hwpx in.hwp out.hwpx --verify --verify-pages --json
$R export-pdf in.hwpx -o out.pdf --backend svg \
  --fallback-serif NanumMyeongjo --fallback-sans NanumGothic --fallback-mono NanumGothicCoding --json
$R export-text in.hwpx --json          # 페이지 0 기준
$R dump-pages in.hwpx --json           # paraIndex·pageIndex·textPreview(untrusted)
$R digest in.hwpx --sections --json    # 절 제목·쪽
```

격리 worker 조건 실측(현재 처리기, 142 재현에 쓴 형태):

```bash
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 \
  --cap-drop=ALL --security-opt no-new-privileges \
  -v /home/jechoi/projects/bidops:/app:ro -v "$IN:/input:ro" -v "$OUT:/out:rw" \
  --workdir /app/web/backend --entrypoint /usr/local/bin/python <image> /probe.py
# probe.py 첫 줄: import sys; sys.path.insert(0, "/app/web/backend")
```

worker 재생성(이미지 고정 overlay, 운영 단계에서만):

```bash
docker compose --env-file .env -p bidops -f docker-compose.yml -f <overlay.json> \
  up -d --no-deps --no-build --force-recreate document-worker
```

v4 준비(활성화가 필요하며 endpoint가 없으면 `--binding`): [operations.md "사전규격 v4 준비"](../operations.md). binding·renderer·font JSON은 직전 활성화 감사와 35 snapshot의 `renderer_jsonb`/`font_jsonb`에서 복원한다. config JSON은 `{"options": vars(ProcessorOptions.from_mapping(options))}`여야 한다.

테스트(호스트 venv, [tracking 기준선은 memory가 아니라 status.md](../tracking/status.md)):

```bash
cd web/backend && .venv/bin/python -m pytest tests/deep_review/test_document_mcp.py -q --tb=short
docker compose --env-file .env -f docker-compose.yml config --quiet
git diff --check
```

## 4. 단계별 계획

정의(내용·게이트)는 Spec §7이 정본이다. 여기에는 담당·브랜치·소유 파일·체크리스트만 둔다.

### R0 기준선 (담당: 격리 stage worker 구현·실측, 관리자 독립 검토·병합)

- [x] vendor 등록: `web/backend/app/deep_review/document_mcp/vendor/rhwp/bin/rhwp`, `vendor/SHA256SUMS` 갱신, `vendor/PROVENANCE.md`에 upstream·태그·커밋·빌드 host·명령 기록(ADR-RDP-002).
- [x] `web/Dockerfile`에 `fonts-nanum` 추가, rhwp COPY와 실행 권한. 검증용 이미지 `bidops-rdp-r0:<날짜>` 빌드(context는 저장소 루트).
- [x] 격리 컨테이너(위 명령, pids 128)에서 표본 3건에 해당 rhwp 호출 실행. 시간·RSS·pids 최대치·페이지 수·바이트 크기 기록.
- [x] 같은 입력 2회 실행으로 HWPX·페이지 텍스트·dump-pages JSON·PDF 바이트 동일 여부 기록. PDF 결정성은 같은 검증 이미지의 세 표본에서만 확인한 증거로 보존하며 보편적 보증으로 확대하지 않는다.
- [x] `dump-pages`의 `paraIndex`가 표 셀 문단을 포함하지 않고 구역별 최상위 본문 문단을 가리킴을 upstream 코드와 실측으로 확정. identity는 항상 `(section, paraIndex)`로 하고, 원본 HWPX는 extractor identity가 증명된 경우에만 source XML top-level ordinal을 사용한다. HWP→HWPX ordinal crosswalk 부재는 exact full-text 단일 페이지 매치만 허용하는 보수적 지원 동작으로 확정한다.
- [x] 결과를 Spec §8과 이 문서 §7에 기록하고 `docs/validation-runs/<날짜>-rhwp-r0-baseline.md`에 재현 명령을 남긴다.

게이트: 표본 3건이 pids 128 이하·60초 안 통과, 네 native JSON 호출의 호출별 stdout 1 MiB(1,048,576 B) 상한을 수용하고 실제 최대 747,110 B를 기록, `(section, paraIndex)` 규칙과 보수적 HWP 매핑 동작을 확정, `test_vendored_sha256_manifest_is_deterministic_and_complete` 통과. 매핑률은 F5에 따라 정보성 지표이며 게이트가 아니다.

### R1 변환기 (담당: 위임, `feat/rdp-r1-converter`)

- [x] `DocumentProcessor`에 rhwp 경로([Spec §1](Spec.md#1-rhwp-호출-계약) ①~⑤). Canvas 경로는 남기고 검증된 `renderer` 값으로 명시 선택하며 기본값은 기존 경로다.
- [x] stdout JSON 파서, `untrustedFields` 처리, 오류 코드([Spec §5](Spec.md#5-오류-코드)), 페이지 번호 0→1 변환. 네 native 호출별 stdout cap은 1 MiB이며 초과는 `output_size_limit`이다.
- [x] `_run_limited_subprocess` 아래 공유 deadline·stdout cap·per-artifact output cap·일반 rlimit. stdout을 무제한으로 열거나 파일 출력으로 우회하지 않으며, Chromium 예외(AS/DATA 해제, FSIZE 4배)는 미적용.
- [x] `tests/deep_review/test_document_mcp.py`에 rhwp 계약 테스트(고정 JSON으로 파서·오류·페이지 일치. 실제 바이너리 실행은 이미지 안 실측으로만).
- 소유 파일: `document_mcp/processor.py`, `contracts.py`, `errors.py`, `safety.py`(옵션), 해당 테스트.

게이트: focused 테스트, 격리 이미지에서 표본 3건 산출물 5종, 금액·기간·ID 보존([Requirements §6](Requirements.md#6-표본과-측정-기준선)).

### R2 대응표 (담당: 사용자 요청에 따라 직접 구현, `feat/rdp-r2-para-page-map`)

- [x] 정렬기 `para-page-align.v1`(R0에서 확정한 Spec §4) 구현.
- [x] `bidops.para-page-map.v1`([Spec §2](Spec.md#2-산출물과-저장)) 생성·검증(schema, 결정성, 매핑률).
- [x] 테스트: 정상·페이지 걸침·빈 문단·표 셀·개수 불일치·미매핑.
- 소유 파일: `document_mcp/para_page_map.py`(신규), `contracts.py`, 해당 테스트. extractor identity를 같은 XML 순회에서 증명하고 실제 변환 결과로 전달하기 위해 `hwpx.py`·`native.py`·`processor.py`도 연결했다. 구조 JSON 계약은 유지하고 대응표·바이트는 `ProcessedDocument` 속성으로만 제공한다. DB·scratch sidecar 저장은 R3다.

게이트: 2회 실행 바이트 동일, 표본 매핑률 기록, 미매핑이 문서 실패로 번지지 않음.

### R3 저장·snapshot (담당: 사용자 요청에 따라 직접 구현, `feat/rdp-r3-snapshot`)

- [x] Alembic 0023: [Design §2.4](Design.md#24-데이터-모델) nullable 열, `renderer` 값 확장, worker INSERT 권한(`scripts/runtime-privileges.sql`). 같은 migration에 검증기 경고 열 `validation_warnings` jsonb(WP-3 `pdf_inline_locator_normalized`의 저장 자리, [ADR "관련 결정"](ADR.md#관련-결정이-작업-밖-참조))와 `web/backend/tests/app/test_module_boundaries.py`가 검사하는 §5.1 테이블 소유표에 `prespec_v4_attempt`를 추가(기존 실패 해소).
- [x] `prepare_v4_pdf_snapshot`: 산출물 6종 저장·결속, `renderer_digest` 재정의, 캐시 재사용 검증에 HWPX·대응표 포함.
- [x] 준비 실패 코드 `pdf_preparation_failed:<code>`와 감사 `converter_code`([findings "pdf_preparation_failed가 실제 오류 코드를 감춘다"](../tracking/findings.md)).
- [x] `document_converter.py`·`document_protocol.py` v2 sidecar에 HWPX·페이지 텍스트·대응표 파일(원자 publish, hash 검증).
- [x] 테스트: 임시 PostgreSQL 17 migration·trigger·권한, 격리 roundtrip, 캐시 재사용.

- 소유 파일: `core/db.py`(runtime revision), `models.py`, `alembic/versions/0023_*.py`, `scripts/runtime-privileges.sql`, `services/prespec_v4.py`, `services/document_converter.py`, `document_protocol.py`, `services/prespec_v4_runner.py`(실패 감사), `services/document_structures.py`(공유 materialization), `document_mcp/native_artifacts.py`(공유 검증), 해당 테스트, `docs/database-guide.md`·`docs/deep-review-erd.md` 해당 절.

게이트: PostgreSQL smoke·roundtrip, 기존 행 미변경, `test_module_boundaries` 통과.

검증과 제한: [R3 검증 기록](../validation-runs/2026-09-10-rhwp-r3-snapshot.md). 같은 문서 버전의 기존 구조와 pages·blocks가 다르면 보존 후 실패하며, 구조 revision 재설계는 포함하지 않는다. 실제 MinIO·ClamAV 운영 인수는 R6에 남긴다.

### P1 병합 (담당: 관리자)

- [x] `feat/p1-wp1-model-client` → `-wp2-validation-retry` → `-wp3-citation-normalize` 순으로 main 병합(`bbbbaae`).
- [x] WP-3의 경고를 R3의 `validation_warnings`에 저장하도록 연결(`feat/p1-wp4-validation-warnings` 63b6ef4, main 병합).

- 시점: P2 실측을 먼저 볼 수 있으면 그 뒤, 늦어도 R4 전.

### R4 소비자 (담당: 위임, `feat/rdp-r4-consumers`)

- [x] page-overview·회사 핏·근거 PDF endpoint의 renderer 이름 교체([Design §2.5](Design.md#25-소비자-연결)). 확인 결과 소비자 계층(`page_overview`·`company_fit*`·`prespec_v4_runner`·REST schema)에 renderer 문자열이 없어 코드 변경 없이 성립한다.
- [x] `document-segments.v1`에 `page_range`·`mapping_status`([Spec §6](Spec.md#6-rest화면-변경)), `docs/contracts.md` 갱신. 조회 시점에 대응표를 가진 최신 native snapshot에서 계산하며 저장하지 않는다. 링크용 `GET /api/document-structures/{id}/pdf` 추가.
- [x] 심층 검토 보고서·segment 화면에 PDF 페이지 링크, 없으면 "페이지 미확인". `partial`은 "일부 블록만 대응" 문구.
- [x] focused backend 147 passed·1 skipped, `deep-review.spec.ts` 17 passed(1440×900), `overflow.spec.ts -g deep-review` 8 passed(1280×800·1440×900).

- 소유 파일: `services/page_overview.py`, `services/company_fit.py`, `services/document_segments.py`, `routers/deep_reviews.py`, `contracts/bidops.document-segments.v1.json`, frontend 해당 컴포넌트·spec, `docs/contracts.md`.

게이트: API 계약 테스트, 두 폭 화면, contracts.md 갱신.

### R5 제거 (담당: 위임, `feat/rdp-r5-remove-chromium`)

- [x] Canvas HTML builder, receipt 검사, Chromium·Node 지문, `rhwp.js`·`rhwp_bg.wasm`·`rhwp_convert.mjs`·`rhwp_render_canvas.mjs` 삭제([Design §5](Design.md#5-마이그레이션과-호환)). `PROVENANCE.md`·`SHA256SUMS` 정리. `processor.py` 1607→905줄, renderer는 `rhwp-svg-pdf` 하나이며 HWP·HWPX는 항상 native 경로다.
- [x] Dockerfile에서 chromium·chromium-sandbox·nodejs 제거, compose Chromium용 완화 제거(다른 완화는 없었음), `pids_limit` 128(R0 실측 최대 4), `tests/app/test_runtime_contract.py` 갱신. 이미지 `bidops-rdp-r5:20260910` 2.03GB→1.04GB, chromium·node 부재·rhwp v0.8.6·Nanum 폰트 확인.
- [x] 전체 backend 스위트와 화면 스위트 각 1회. 기존 실패는 아래 §7 R5 행과 [findings.md](../tracking/findings.md)에 목록으로 남김.

- 소유 파일: `document_mcp/processor.py`, vendor 디렉터리, `web/Dockerfile`, `docker-compose.yml`, runtime contract 테스트, `docs/operations.md`·`docs/security.md` 해당 절.

게이트: 이미지에 chromium·node 없음, 전체 스위트 결과가 기존 실패 목록과 같거나 줄어듦.

### R6 운영 인수 (담당: 관리자, 승인 범위 안)

- [x] DB·MinIO 백업(owner dump 22.5 MB + 객체 960 version hash manifest) → 0023 migration(`run --rm --no-deps --pull never migrate`, 이미지 고정 overlay) → runtime 권한 재적용. 기존 행 3·3·7·165 불변.
- [x] 새 이미지 `bidops-rdp-r6:20260910`로 web·document-worker 재생성. R5 이미지의 `fc-list` 부재(native 변환 전부 `converter_unavailable`)를 `web/Dockerfile` `fontconfig` 추가로 먼저 보정했다.
- [x] explicit_sample 활성화 → 142·59 native snapshot·target `ready` → 비활성화. endpoint가 없어 attempt는 없다. **35는 보류**: 새 구조 blocks가 기존과 달라 `structure_binding_mismatch`가 나고 실패 attempt가 `current`를 덮으므로 실행하지 않았다.
- [x] API·UI 확인: `overview-pages` 35/59/142 준비 전후 byte 동일, 142 segments `mapped` 35·`partial` 42, 구조 PDF endpoint 200(4,829,134 B), 두 폭 화면 오버플로·오류 없음. 심층 검토 화면의 segment 링크는 운영 `deep_review` 행이 없어 REST로만 확인.
- [x] `docs/tracking/status.md`·`findings.md`·`prespec-v4-implementation-plan.md`·[`docs/validation-runs/2026-09-10-rhwp-pipeline.md`](../validation-runs/2026-09-10-rhwp-pipeline.md) 기록.

게이트: 세 표본 중 142·59 새 snapshot과 142 화면 링크 경로(REST) 확인, 기존 결과 보존, 문서 갱신. 35는 구조 revision 설계·승인 뒤 별도로 준비한다.

### R7 범위 선택 보조 (담당: 위임, 별도 승인 뒤)

- [x] `digest --sections --json` 후보 생성·저장: 산출물 ⑦ `bidops.section-candidates.v1`, sidecar·객체·0024 nullable 참조(WP-A `8b1c077`). 142 격리 실측 43절 `clause`.
- [x] 결정적 선택기가 `ready`가 아니면 실패 attempt 대신 `needs_human_review` target을 동결하고, LLM 보조는 CLI `--assist-range`로만 실행해 감사 행(제안)으로 남긴다([ADR-RDP-004](ADR.md#adr-rdp-004-변환은-프로그램이-해석범위-선택-보조역할별-분석은-llm이-맡는다), WP-B `5a5646d`).
- [x] 사람이 후보를 확인·확정하는 화면 경로: `range_review` 투영 + `POST …/range-confirmations` + 사전규격 상세 `개요 범위 확인` 카드(WP-C `ae80dae`). 확정은 `human_confirmed` ready target만 만들고 attempt를 열지 않는다.
- [x] 운영 반영: 백업 → 0024 → web·worker `bidops-rdp-r7:20260910` 재생성, 기존 응답 불변([R7 기록](../validation-runs/2026-09-10-rhwp-r7-range-review.md)).

게이트: 자동 실행을 열지 않음(테스트·운영 409/404로 확인). **표본에서의 사람 확정 흐름은 운영에서 재현하지 못했다** — 세 표본 모두 heading 선택기가 `ready`라 확정 대기 target이 없고, 흐름은 API 종단 테스트와 Playwright 목 검사로 확인했다. 실제 확정 대기 문서가 들어오면 운영에서 확인한다.

## 5. 역사적 곁줄기 (2026-09-10 당시 Qwen 전환 준비)


| 항목                                 | 선행 조건                                                            | 시점             | 참조                                                                                           |
| ---------------------------------- | ---------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------------- |
| P2 Qwen 검증기 통과율 실측, 142 attempt 실행 | overview endpoint 복구, `max-model-len`·`enable_thinking` kwarg 확인 | endpoint 복구 즉시 | [operations.md "참조 실행"](../operations.md), [model-quality-gate.md](../model-quality-gate.md) |
| P1 병합                              | P2 결과가 있으면 그 뒤, 늦어도 R4 전                                         | §4             | [ADR "관련 결정"](ADR.md#관련-결정이-작업-밖-참조)                                                         |
| P3 정책 v5                           | R4 뒤                                                             | R6 뒤           | 정책 파일 `policies/prespec-overview-policy-v4.json`·`prompt-v4.md`를 v5로 복제                      |


## 6. 역사적 작은 정리 (2026-09-10 당시)

- `docs/design/*.hwp` 실표본 2건과 `Zone.Identifier`: 저장소 보관 여부 결정. 보관하지 않으면 [Requirements §6](Requirements.md#6-표본과-측정-기준선)의 표본 경로를 MinIO 원본으로 바꾼다.
- 세션 scratchpad에만 있던 실측 스크립트(`probe142*.py`, rhwp 실측 명령)는 R0에서 `docs/validation-runs/`에 재현 명령으로 남긴다.
- `docs/tracking/findings.md`의 두 신규 항목 중 `pdf_preparation_failed` 은폐는 R3에서 닫았다. attempt 없는 ready target 미표시(`current` projection)는 R4 범위(Spec §6·Design §2.5)에 들어 있지 않아 **아직 열려 있다**. R6는 이를 닫지 않은 채 진행했고, 142의 새 target `f7c73503-…`도 `current`에 드러나지 않는다(2026-09-10).

## 7. 진행 기록

| 일자 | 단계 | 내용 |
|---|---|---|
| 2026-09-09 | 선행 | 142 timeout 원인 확정(pids 128·출력 예산 20 MiB), P0 브랜치, P1 WP-1~3 브랜치(미병합). 근거: [findings 142 항목](../tracking/findings.md) |
| 2026-09-10 | 선행 | P0 main 병합(`212e5ed`), worker pids 512 재생성, 142 snapshot `e68670e0…`·target `200e9557…` 준비(attempt 없음), 기록 `695e245` |
| 2026-09-10 | 착수 | rhwp v0.8.6 호스트 실측(표본 3건, [Spec §8](Spec.md#8-실측-기록)), 사용자 결정 4개(ADR-RDP-001~004), 정본 문서 4종 `2f4f6af`, 이 계획 작성. 다음: R0 |
| 2026-09-10 | R0 | Orca 관리 격리 worktree `/home/jechoi/orca/workspaces/bidops/rdp-r0-baseline`, 브랜치 `feat/rdp-r0-baseline`에서 native binary·Nanum 폰트 이미지와 표본 2회 실측 완료. pids·시간·결정성은 통과했지만 `dump-pages` stdout 256 KiB 초과와 HWP→HWPX paragraph crosswalk 미정 때문에 R0 게이트는 닫힘. 근거: [validation run](../validation-runs/2026-09-10-rhwp-r0-baseline.md) |
| 2026-09-10 | R0 계약 종결 | 최초 실측 시점의 닫힌 게이트 기록은 유지한다. 이미 측정한 세 표본의 안전 지표를 근거로 native 네 호출별 stdout cap을 1 MiB(1,048,576 B)로 정하고 실제 최대 747,110 B를 기록했다. identity는 `(section, paraIndex)`로 고정하고, extractor identity가 증명된 원본 HWPX만 source XML ordinal을 쓰며 HWP→HWPX는 exact full-text가 정확히 한 export-text 페이지에 한 번 나타날 때만 매핑한다(그 외·빈 블록은 `unmapped`). PDF 결정성은 같은 이미지의 세 표본 재실행 증거에만 한정한다. R0 게이트를 통과로 종결했으며 현재는 R1 시작에 대한 coordinator acceptance를 기다린다. |
| 2026-09-10 | R0 수락 | coordinator가 R0를 수락하고 main `518a770`에 병합했다. R1은 이 commit에서 시작했다. |
| 2026-09-10 | R1 | `feat/rdp-r1-converter`에서 명시적 `rhwp-svg-pdf` 선택 seam, 엄격 native JSON/산출물 검증, out-of-band HWPX·PDF·page-text·sanitized dump와 worker 계산 provenance를 구현했다. focused 54건과 변경 후 대상 검사, R0 이미지의 세 표본 실제 `DocumentProcessor` 경로가 통과했다. 근거: [R1 validation](../validation-runs/2026-09-10-rhwp-r1-converter.md), [safe metrics](../validation-runs/2026-09-10-rhwp-r1-converter.metrics.json). 다음 단계는 coordinator가 diff와 증거를 수락한 뒤에만 연다. |
| 2026-09-10 | R1 수락·중단 | Sol medium의 구현 `5332e6e`와 Luna max의 경계 보정 `666e7a4`를 관리자가 diff·검증 증거로 검토하고 main에 병합했다. 보정 대상 회귀 검사 16건 통과; 세 표본 실측·전체 스위트·이미지 빌드는 반복하지 않았다. 사용자 요청에 따라 이 단계에서 중단한다. R2는 미착수이며 운영 배포·DB 변경·활성화·모델 호출은 수행하지 않았다. 재개 시 R2부터 시작한다. |
| 2026-09-10 | R2 직접 구현·검증 | 사용자 재개 요청으로 위임 없이 `/home/jechoi/orca/workspaces/bidops/rdp-r2-para-page-map` (`feat/rdp-r2-para-page-map`, 시작점 `41eaef5`)에서 구현했다. source HWPX의 패키지 구역 순서·XML 문단 identity와 dump의 구역별 전체 인덱스 집합을 대조하고, HWP·표 셀은 FULL text 유일 발생만 허용한다. 세 표본 실제 native processor 통과, 대응표 재생성 바이트 동일, 전체 블록 매핑률 36.70%·19.29%·15.45%, 미매핑으로 인한 문서 실패 없음. 근거: [R2 검증](../validation-runs/2026-09-10-rhwp-r2-para-page-map.md)·[안전 지표](../validation-runs/2026-09-10-rhwp-r2-para-page-map.metrics.json). R2 구현 게이트 충족, 단계 검토 전 미커밋·미병합이며 R3는 열지 않았다. 운영 변경·모델 호출 없음. |
| 2026-09-10 | R2 수락·R3 승인 | 사용자가 R2의 main 병합과 R3 계속 진행을 요청했다. 저장된 R2 diff·검증 지표를 확인해 병합하며, 기존 main 계획서의 기능 구현 우선 원칙을 보존했다. R3는 별도 격리 worktree에서 직접 진행하고 운영 migration·배포는 R6에 남긴다. |
| 2026-09-10 | R3 직접 구현·검증 | R2를 main `1db6986`에 fast-forward 병합한 뒤 Orca worktree `/home/jechoi/orca/workspaces/bidops/rdp-r3-snapshot`, `feat/rdp-r3-snapshot`에서 직접 구현했다. nullable 0023·runtime head·worker 권한, native scratch sidecar·객체 version/hash 결속과 캐시, 안전 오류·감사 기록을 연결했다. 최종 관련 회귀 107건, PostgreSQL·권한·경계 50건 및 보정 후 대상 검사가 통과했다(중복 합산 금지). 실제 격리 이미지 세 표본 79/53/31쪽의 저장·캐시 재사용·scratch 정리, R2 대응표 해시 일치를 확인했다. 근거: [R3 검증](../validation-runs/2026-09-10-rhwp-r3-snapshot.md)·[지표](../validation-runs/2026-09-10-rhwp-r3-snapshot.metrics.json). R3 게이트 충족, 미커밋·미병합으로 단계 검토 대기. P1·R4와 운영 변경은 시작하지 않았다. |
| 2026-09-10 | R3 수락·병합 | 사용자가 R3 커밋과 main 병합을 요청했다. 검토한 R3 코드·migration·계약 문서·검증 기록을 함께 커밋하고 main에 fast-forward 병합한다. 검증 뒤 코드 변경이 없어 기존 통과 검사를 반복하지 않고 수락 문서와 staged diff를 확인했다. P1·R4는 아직 시작하지 않았으며 운영 migration·배포·활성화·모델 호출도 수행하지 않았다. |
| 2026-09-10 | P1 병합·R4 착수 | 관리자가 `feat/p1-wp1-model-client`(87cce3b) → `-wp2-validation-retry`(3f03bca) → `-wp3-citation-normalize`(3a3dfab)를 순서대로 main에 병합했다(`bb1045c`·`39dfaff`·`bbbbaae`, 충돌 없음). 병합 트리에서 닿는 백엔드 테스트 5파일(`test_model_client`·`test_page_overview`·`test_company_fit`·`test_prespec_v4_runner`·`test_deep_reviews`) 171 passed 1회. WP-3 경고를 `validation_warnings`에 저장하는 연결은 `feat/p1-wp4-validation-warnings`, R4는 `feat/rdp-r4-consumers`(백엔드)·`feat/rdp-r4-consumers-ui`(프론트엔드)로 `.worktrees/` 아래에서 Opus 서브에이전트에 병렬 위임했다. R4 결정: segment PDF 링크는 구조 기준 endpoint `GET /api/document-structures/{id}/pdf`(대응표를 가진 최신 native snapshot의 PDF)를 새로 두고 segments 계약 추가는 Spec §6의 `page_range`·`mapping_status` 둘뿐이다. 운영 변경·모델 호출 없음. |
| 2026-09-10 | P1 WP-4 수락 | 위임 결과 `63b6ef4`(`_complete` 최종 관문을 `validate_page_overview_detailed`로 바꿔 완료 attempt의 `validation_warnings`와 완료 감사에 경고 목록 저장, 경고 없음은 `[]`, 재시도·실패 경로 미변경)를 diff로 검토하고 main에 병합했다. 위임 검증 `test_prespec_v4_runner`·`test_page_overview` 22 passed 1회, `diff --check` clean. 경고 조건은 검토 페이지가 둘 이상이어야 성립하므로 같은 테스트 파일 안에 3쪽 표본 옵션만 추가했다. |
| 2026-09-10 | R4 수락·병합 | 백엔드 `8725d47`(`feat/rdp-r4-consumers`)과 프론트 `cedcbd1`(`feat/rdp-r4-consumers-ui`)을 diff로 검토하고 main에 병합했다(`4514421`·`506e323`). 대응표 읽기·hash 실패는 조용히 `unavailable`로 낮추지 않고 500 `processing_failed`, 구조 PDF endpoint는 개요 PDF와 같은 무결성 검사 함수(`verified_pdf_bytes`)를 공유한다. 화면 fixture가 사람 확인 segment 1→3건으로 늘어 `screen-semantics.spec.ts` 개수 단언 2줄을 사실대로 고쳤고, 픽셀 층 `deep-review-complete` 기준선은 갱신하지 않았다(승인 뒤 교체). 실제 native snapshot이 있는 응답 확인은 운영 migration이 없어 R6에서 한다. |
| 2026-09-10 | R5 수락·병합 | 위임 `e4e1b9f`(제거)와 보정 `2c0e19f`(PDF v2 protocol 테스트 fake를 native 형태로)를 diff로 검토하고 main에 병합했다(`753d639`). 게이트: 이미지 빌드 후 chromium·node 없음. 최종 트리 전체 backend 스위트 1회 = 1794 passed·5 skipped·33 failed·21 errors, 이 중 47건은 worktree에 없는 gitignore 파일(`experiments/.../company-capabilities-v1-approved.json`) 때문이며 병합된 main에서 같은 파일들 419 passed·14 skipped로 해소; 4건(`test_document_worker_protocol`)은 R5 회귀로 보정 후 14 passed; 남은 3건(`test_alembic_autogenerate` drift, `test_model_has_exact_closed_table_set` 82≠81, `test_mapper_isolation`)은 `a9ddb99`(R3 직후)에서도 실패하는 기존 결함. 화면 `test:screens` 1회 = 499 passed·5 skipped·3 failed, 이 중 2건은 단독 재실행 통과(부하 flake), `common-interactions.spec.ts:211`은 main과 `bbbbaae`에서도 실패하는 기존 결함. 다음 단계 R6(운영 인수)은 열지 않았고 운영 migration·배포·활성화·모델 호출은 수행하지 않았다. |
| 2026-09-10 | R6 운영 인수 | 사용자 요청으로 관리자가 직접 실행했다. 백업(DB dump `481c9974…`, 객체 960 version) 뒤 R5 이미지 격리 실측에서 `fc-list` 부재로 native 변환이 `converter_unavailable`인 R5 회귀를 발견해 `web/Dockerfile`에 `fontconfig`를 추가하고 `bidops-rdp-r6:20260910`을 빌드했다. 0023 migration·권한 적용, web(배포 dir `rdp-r6-20260910-4c9f33ec`)·document-worker(pids 128) 재생성, explicit_sample 활성화 `d73daa62…` → 142 native snapshot `f8a42b74…`(79쪽, 기존 구조 결속, 대응표)·target `f7c73503…`, 59 snapshot `3aa6c47f…`·target `ec040093…` → off `5016643f…`. 35는 새 구조 blocks 1,454 ≠ 기존 1,349로 `structure_binding_mismatch`가 예상돼 준비하지 않았다(실행 시 실패 attempt가 `current`를 덮음). API·두 폭 UI 확인 통과, 기존 결과 불변. 근거: [R6 기록](../validation-runs/2026-09-10-rhwp-pipeline.md). 남은 것: 35 구조 revision, attempt(endpoint), ready target projection, 기존 실패 4건. R7은 열지 않았다. |
| 2026-09-10 | R7 | 사용자 승인 뒤 Opus 서브에이전트 3개에 위임(WP-A 산출물 ⑦·0024, WP-B 선택기 연결·확정 REST·`--assist-range`, WP-C 화면), 관리자가 diff·게이트 검수 후 main 병합(`a0a2039`·`1f66044`). 통합 트리 백엔드 319 passed·프론트 page-overview 9 passed, PostgreSQL 0024 5 passed(WP-A 브랜치). 이미지 `bidops-rdp-r7:20260910` 격리 실측 142 후보 43절. 운영: 백업(`bc699ea6…`) → 0024 → web(`rdp-r7-20260910-cf89169f`)·worker 재생성, API·UI 회귀 없음. 하지 못한 것: 실표본 사람 확정 재현(확정 대기 target 없음), 실제 모델 보조 호출, temperature 0(per-call 인자 없음), non-ready target의 manifest 참조 결속. 근거: [R7 기록](../validation-runs/2026-09-10-rhwp-r7-range-review.md). R0~R7 전 단계 종료. |
| 2026-09-11 | MVP 보완·운영 반영 | section-candidates v2, core/보조 분리, 공백 쪽 보존·근거 거부, 범위 조회 v2·직접 쪽 선택·target PDF, 새 target 현재성, 같은 줄 복수 장 및 `제안개요` 오선택 가드를 구현했다. head 0025를 유지하고 새 migration 없이 최종 image `bidops-prespec-mvp:20260911-advisory-final`로 web·document-worker를 교체했다. 6건 source-only 재준비로 snapshot·target 각 6건을 append했고 최종 집계는 입력 준비 4·수동 범위 11·문서/안전 4, 모델·내용 검증 0이다. 754·755 v2 경고와 exact target PDF를 live 확인했으며 stored target·선택 쪽은 불변이다. optional/거부/roundtrip 고유 scratch 8건과 기존 selector·조회 4건이 통과했고 추가 변환·target·모델 실행은 0이다. |
