# rhwp 문서 변환 파이프라인 진행 계획

작업명: rhwp-document-pipeline · 기준일: 2026-09-10 · 상태: R1 검토·병합 완료, 사용자 요청으로 중단 (다음 R2 미착수)

이 문서는 새 세션이 다른 맥락 없이 이 작업을 이어갈 수 있도록 순서·담당·게이트·현재 상태·재현 명령을 모아 둔다. 내용이 이미 다른 문서에 있으면 여기 다시 적지 않고 링크한다. 단계가 끝나거나 결정이 바뀌면 §7 진행 기록에 덧붙이고, 결정 자체는 [ADR.md](ADR.md)에 적는다.

## 0. 새 세션 시작 절차

1. 저장소 지침 [CLAUDE.md](../../CLAUDE.md)와 [docs/standards.md](../standards.md), [docs/engineering-notes.md](../engineering-notes.md), [web/backend/AGENTS.md](../../web/backend/AGENTS.md)를 읽는다.
2. 이 작업의 정본 네 문서를 순서대로 읽는다. [ADR.md](ADR.md)(결정 7개와 트레이드오프) → [Requirements.md](Requirements.md)(F1~F11, N1~N8, 표본·인수 기준) → [Design.md](Design.md)(목표 구조, 데이터 모델, 실패 처리) → [Spec.md](Spec.md)(rhwp 호출 계약, 산출물 schema, 정렬 규칙, 오류 코드, 단계 정의, 실측표).
3. §7 진행 기록에서 마지막 줄을 보고 어느 단계가 열려 있는지 확인한다. 열린 단계의 브랜치가 있으면 `git worktree list`로 위치를 찾는다.
4. 현재 운영 상태는 [docs/tracking/status.md](../tracking/status.md) "사전규격 v4 최신 운영 상태"와 [docs/tracking/findings.md](../tracking/findings.md)의 notice 142 항목, [prespec-v4-implementation-plan.md](../tracking/prespec-v4-implementation-plan.md) "최신 운영 상태"에 있다.
5. 운영 명령(compose, 배포, v4 CLI, 참조 실행)은 [docs/operations.md](../operations.md)를 따른다. 특히 "사전규격 v4 준비" 절과 2026-09-10에 추가된 `--binding` 주석.

## 1. 진행 원칙

- 단계(R0~R7)는 [Spec.md §7](Spec.md#7-단계와-게이트)의 정의를 따르고 한 번에 하나만 연다. 게이트를 못 넘으면 다음 단계를 열지 않고 같은 단계를 보정해 다시 위임한다.
- 판단은 단계 사이에 사람이 내리고 이 문서와 ADR에 적는다. 위임 프롬프트에는 선택지를 남기지 않는다.
- 구현과 실측은 단계마다 별도 브랜치·격리 worktree(`feat/rdp-r<n>-<이름>`)의 stage worker에게 위임하고, 관리자가 diff와 저장된 안전 지표·테스트를 직접 확인한 뒤에만 main에 병합한다. Orca가 관리하는 worktree는 `.worktrees/` 밖의 Orca workspace 경로일 수 있으며 실제 경로를 진행 기록에 남긴다. 위임 보고만을 근거로 쓰지 않는다. 파일 소유가 겹치는 작업은 같은 단계 안에서 순차로 한다.
- 검증은 변경 파일이 닿는 테스트만 돌린다([CLAUDE.md "검증 범위와 종료 기준"](../../CLAUDE.md)). 전체 backend 스위트와 화면 스위트는 R5 뒤 최종 트리에서 각 1회다. 통과를 얻기 위한 반복 실행·검사 완화·재시도 루프를 넣지 않는다.
- 운영 상태 변경(migration, worker 재생성, 활성화, 실제 모델 호출)은 R6에서만, 백업 뒤에, 승인 범위 안에서 한다.
- 기존 강제 게이트(원본 불변, unknown 보존, 자동 보정 금지, 외부 전송 금지, 참조 실행 표식 `unmeasured_reference`)를 그대로 지킨다([CLAUDE.md "강제 게이트"](../../CLAUDE.md)).

## 2. 현재 상태 (2026-09-10 기준, 새 세션이 먼저 확인할 것)

| 항목 | 상태 | 확인 방법 |
|---|---|---|
| main | `2f4f6af` (정본 문서 4종) ← `695e245`(142 재실행 기록) ← `212e5ed`(P0 병합) ← `eb2ffe5`(docs/ops) | `git log --oneline -5` |
| 미병합 브랜치 | `feat/p1-wp1-model-client`(87cce3b), `feat/p1-wp2-validation-retry`(3f03bca, WP-1 위), `feat/p1-wp3-citation-normalize`(3a3dfab). 내용은 [ADR.md "관련 결정"](ADR.md#관련-결정이-작업-밖-참조) | `git worktree list`, `git branch --list 'feat/p1*'` |
| 운영 컨테이너 | Compose 프로젝트 `bidops`. web `bidops-web-1`(이미지 `bidops-prespec-canvas100:20260909`, 127.0.0.1:18887), document-worker 2개(이미지 `bidops-v4-luna-reference:20260909-final`, pids 512로 2026-09-10 재생성) | `docker ps`, `docker inspect <c> --format '{{.HostConfig.PidsLimit}}'` |
| 배포 설정 보관 | `~/.local/state/bidops/deployments/<이름>-<id>/deploy.compose.json` | [operations.md "화면 노출과 edge overlay"](../operations.md) |
| v4 activation | OFF (마지막 감사 `31bee035-…`) | `select safe_metadata from bidops.audit_event where action='prespec_v4.activation' order by created_at desc limit 1` |
| notice 142 | snapshot `e68670e0-4bf7-4cd9-baa1-174f19e5e994`(Canvas renderer, 85쪽), target `200e9557-d5d5-4a0f-afa8-896d44b41261` ready, attempt 없음 | [findings.md 142 항목](../tracking/findings.md) |
| notice 35/59 | Canvas renderer snapshot과 Luna 참조 결과 completed/current | [status.md](../tracking/status.md) |
| 모델 endpoint | overview vLLM `192.168.0.139:58765` 응답 없음(2026-09-09~10). `env/vllm.env`는 TEST-NET 자리표시자 | `curl -m 5 http://192.168.0.139:58765/v1/models` |
| rhwp 호스트 빌드 | `/home/jechoi/projects/rhwp/target/release/rhwp` v0.8.6, 커밋 `cac9b4f7c`, SHA-256 `c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c`. 아직 vendor에 없음 | `sha256sum`, `git -C /home/jechoi/projects/rhwp describe --tags` |
| 표본 | 142 원본은 MinIO `source/7cc3b5f3894d984c-6f70b025586e46bdbe159ca4167a4e86.hwpx`(version `c11572d1-…`). HWP 2건은 `docs/design/(공고 2026-25) 제안요청서.hwp`·`과업지시서.hwp`(untracked, notice 10) | Requirements §6 |
| 폰트 | 호스트에 Nanum 3종 있음, worker 이미지에는 Noto CJK만 | `fc-list : family` |

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

### R2 대응표 (담당: 위임, `feat/rdp-r2-para-page-map`)

- [ ] 정렬기 `para-page-align.v1`(R0에서 확정한 Spec §4) 구현.
- [ ] `bidops.para-page-map.v1`([Spec §2](Spec.md#2-산출물과-저장)) 생성·검증(schema, 결정성, 매핑률).
- [ ] 테스트: 정상·페이지 걸침·빈 문단·표 셀·개수 불일치·미매핑.
- 소유 파일: `document_mcp/para_page_map.py`(신규), `contracts.py`, 해당 테스트.

게이트: 2회 실행 바이트 동일, 표본 매핑률 기록, 미매핑이 문서 실패로 번지지 않음.

### R3 저장·snapshot (담당: 위임, `feat/rdp-r3-snapshot`)

- [ ] Alembic 0023: [Design §2.4](Design.md#24-데이터-모델) nullable 열, `renderer` 값 확장, worker INSERT 권한(`scripts/runtime-privileges.sql`). 같은 migration에 검증기 경고 열 `validation_warnings` jsonb(WP-3 `pdf_inline_locator_normalized`의 저장 자리, [ADR "관련 결정"](ADR.md#관련-결정이-작업-밖-참조))와 `web/backend/tests/app/test_module_boundaries.py`가 검사하는 §5.1 테이블 소유표에 `prespec_v4_attempt`를 추가(기존 실패 해소).
- [ ] `prepare_v4_pdf_snapshot`: 산출물 6종 저장·결속, `renderer_digest` 재정의, 캐시 재사용 검증에 HWPX·대응표 포함.
- [ ] 준비 실패 코드 `pdf_preparation_failed:<code>`와 감사 `converter_code`([findings "pdf_preparation_failed가 실제 오류 코드를 감춘다"](../tracking/findings.md)).
- [ ] `document_converter.py`·`document_protocol.py` v2 sidecar에 HWPX·페이지 텍스트·대응표 파일(원자 publish, hash 검증).
- [ ] 테스트: 임시 PostgreSQL 17 migration·trigger·권한, 격리 roundtrip, 캐시 재사용.
- 소유 파일: `models.py`, `alembic/versions/0023_*.py`, `scripts/runtime-privileges.sql`, `services/prespec_v4.py`, `services/document_converter.py`, `document_protocol.py`, `services/prespec_v4_ops.py`, 해당 테스트, `docs/database-guide.md`·`docs/deep-review-erd.md` 해당 절.

게이트: PostgreSQL smoke·roundtrip, 기존 행 미변경, `test_module_boundaries` 통과.

### P1 병합 (담당: 관리자)

- [ ] `feat/p1-wp1-model-client` → `-wp2-validation-retry` → `-wp3-citation-normalize` 순으로 main 병합. WP-3의 경고를 R3의 `validation_warnings`에 저장하도록 연결.
- 시점: P2 실측을 먼저 볼 수 있으면 그 뒤, 늦어도 R4 전.

### R4 소비자 (담당: 위임, `feat/rdp-r4-consumers`)

- [ ] page-overview·회사 핏·근거 PDF endpoint의 renderer 이름 교체([Design §2.5](Design.md#25-소비자-연결)).
- [ ] `document-segments.v1`에 `page_range`·`mapping_status`([Spec §6](Spec.md#6-rest화면-변경)), `docs/contracts.md` 갱신.
- [ ] 심층 검토 보고서·segment 화면에 PDF 페이지 링크, 없으면 "페이지 미확인".
- [ ] focused backend와 영향 spec만(Playwright `page-overview`·`company-fit`·`deep-review` 관련), 1280×800·1440×900.
- 소유 파일: `services/page_overview.py`, `services/company_fit.py`, `services/document_segments.py`, `routers/deep_reviews.py`, `contracts/bidops.document-segments.v1.json`, frontend 해당 컴포넌트·spec, `docs/contracts.md`.

게이트: API 계약 테스트, 두 폭 화면, contracts.md 갱신.

### R5 제거 (담당: 위임, `feat/rdp-r5-remove-chromium`)

- [ ] Canvas HTML builder, receipt 검사, Chromium·Node 지문, `rhwp.js`·`rhwp_bg.wasm`·`rhwp_convert.mjs`·`rhwp_render_canvas.mjs` 삭제([Design §5](Design.md#5-마이그레이션과-호환)). `PROVENANCE.md`·`SHA256SUMS` 정리.
- [ ] Dockerfile에서 chromium·chromium-sandbox·nodejs 제거, compose Chromium용 완화 제거, `pids_limit`을 R0 실측값으로 재설정, `tests/app/test_runtime_contract.py` 갱신.
- [ ] 전체 backend 스위트와 화면 스위트 각 1회. 기존 실패는 목록으로 보고.
- 소유 파일: `document_mcp/processor.py`, vendor 디렉터리, `web/Dockerfile`, `docker-compose.yml`, runtime contract 테스트, `docs/operations.md`·`docs/security.md` 해당 절.

게이트: 이미지에 chromium·node 없음, 전체 스위트 결과가 기존 실패 목록과 같거나 줄어듦.

### R6 운영 인수 (담당: 관리자, 승인 범위 안)

- [ ] DB·MinIO 백업([operations.md 백업·복구](../operations.md)) → 0023 migration → runtime 권한 재적용.
- [ ] 새 이미지로 web·document-worker 재생성(배포별 compose json 절차).
- [ ] explicit_sample 활성화 → 35/59/142 새 snapshot·target 준비 → 비활성화. endpoint가 있으면 attempt까지, 없으면 `ready`까지.
- [ ] API·UI 확인(page-overview, PDF 링크, segments `page_range`), 기존 행 미변경.
- [ ] `docs/tracking/status.md`·`findings.md`·`prespec-v4-implementation-plan.md`·`docs/validation-runs/<날짜>-rhwp-pipeline.md` 기록.

게이트: 세 표본 새 snapshot과 화면 링크, 기존 결과 보존, 문서 갱신.

### R7 범위 선택 보조 (담당: 위임, 별도 승인 뒤)

- [ ] `digest --sections --json` 후보 생성·저장.
- [ ] 결정적 선택기가 `unknown`일 때만 LLM 보조 선택, 결과는 `needs_human_review`([ADR-RDP-004](ADR.md#adr-rdp-004-변환은-프로그램이-해석범위-선택-보조역할별-분석은-llm이-맡는다)).
- [ ] 사람이 후보를 확인·확정하는 화면 경로.

게이트: 자동 실행을 열지 않음, 표본에서 사람 확정 흐름 확인.

## 5. 곁줄기 (Qwen 전환 준비)

| 항목 | 선행 조건 | 시점 | 참조 |
|---|---|---|---|
| P2 Qwen 검증기 통과율 실측, 142 attempt 실행 | overview endpoint 복구, `max-model-len`·`enable_thinking` kwarg 확인 | endpoint 복구 즉시 | [operations.md "참조 실행"](../operations.md), [model-quality-gate.md](../model-quality-gate.md) |
| P1 병합 | P2 결과가 있으면 그 뒤, 늦어도 R4 전 | §4 | [ADR "관련 결정"](ADR.md#관련-결정이-작업-밖-참조) |
| P3 정책 v5 | R4 뒤 | R6 뒤 | 정책 파일 `policies/prespec-overview-policy-v4.json`·`prompt-v4.md`를 v5로 복제 |

## 6. 작은 정리

- `docs/design/*.hwp` 실표본 2건과 `Zone.Identifier`: 저장소 보관 여부 결정. 보관하지 않으면 [Requirements §6](Requirements.md#6-표본과-측정-기준선)의 표본 경로를 MinIO 원본으로 바꾼다.
- 세션 scratchpad에만 있던 실측 스크립트(`probe142*.py`, rhwp 실측 명령)는 R0에서 `docs/validation-runs/`에 재현 명령으로 남긴다.
- `docs/tracking/findings.md`의 두 신규 항목(`pdf_preparation_failed` 은폐, attempt 없는 ready target 미표시)은 R3·R4에서 닫는다.

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
