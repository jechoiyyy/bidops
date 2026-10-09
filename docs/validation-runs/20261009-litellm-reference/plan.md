# LiteLLM 연결과 로컬 개요 참조 실행

2026-10-09 사용자 요청: LiteLLM 기준으로 동작하도록 BidOps를 변경하고, 실제 3일 수집 자료로 첨부 준비와 Qwen 개요 분석까지 진행한다. 기존 DEMO-00의 운영 1489 인수나 DEMO-01 착수 완료로 대체하지 않는다. 기존 활성 run 작업 공간에서 이 실행을 지원하는 변경으로 수행하며 커밋·병합·push는 이번 요청에 포함하지 않는다.

## 계약과 수용 조건

- 연결 설정 `BIDOPS_VLLM_{SCREENING,OVERVIEW,DEEP_REVIEW}_API_DIALECT`에 `litellm`을 추가한다. 기존 두 값과 기본값 유지. GATEWAY_URL/KEY는 로컬 secret 배포 입력이며 모델 client에 전역 fallback으로 연결하지 않는다.
- LiteLLM은 승인 base의 `/models`에서 요청 별칭을 검사하고, 같은 origin/base prefix의 `/model/info`에서 동일 `model_name` 행만 읽는다. `/v1` 말단만 제거한다. 인증·redirect 금지·응답 크기·timeout·안전 오류는 기존 transport와 같다. 반환 upstream URL·key는 사용하거나 로그에 내지 않는다.
- 별칭의 모든 배포에서 양의 정수 `model_info.max_input_tokens`를 요구한다. 여러 배포 값이 다르면 최솟값을 보수적인 전체 요청 상한으로 사용한다. 출력 예약·JSON schema·UTF-8 byte 상계까지 기존 capacity 검사에 포함한다. 누락·bool·음수·잘못된 shape·등록되지 않은 별칭은 호출 전에 거부한다. 선언 revision이 있으면 제공된 revision과 불일치를 거부한다. upstream 모델 이름으로 용량을 추정하지 않는다.
- 기존 구조화 출력·generation 값·bounded retry·외부 fallback 금지 유지. 같은 요청의 모델 별칭은 policy/run/client에 일치해야 한다.
- 별도 immutable 정책 `prespec-overview-policy-v7-litellm-v1.json`: v7의 의미·schema·generation·검증·한도 그대로, model_name=local-agent-main, model_endpoint_ref=litellm-openai-compatible, prompt_version=prespec-overview-v7-litellm-v1. 기존 v7/v8 불변. 새 정책은 로컬에서 명시적으로만 선택한다.
- 개요 전송 전 선택 공고·페이지·전송 정보 미리보기와 사람 승인 필요. 자동 개요/심층/회사핏/스케줄러는 켜지 않는다. 실제 모델 분석 실패도 그대로 남긴다.

## 작업 순서

1. STEP-L01 [complex] transport/config/Compose/example에 LiteLLM 지원. model client 검사: 별칭 성공·누락, 권한/redirect, metadata shape, 용량 상계, 다중 배포 최솟값, revision, 기존 vLLM/Ollama 회귀. 실행자는 리더.
2. STEP-L02 [complex] 별도 v7 LiteLLM 정책과 loader 허용, 정책 불변 테스트, 운영 문서. v7/v8 hash 대조 및 overview 관련 단위 검사.
3. STEP-L03 [complex] 독립 코드 리뷰, 로컬 이미지·실서버 metadata 확인. 첨부 실패 원인을 분리하고 유효 문서 준비 후 승인된 1건 개요 실행·화면 확인. 실제 완료 전 참조 결과를 성공으로 기록하지 않는다.

## 현재 실행 증거

`.sdlc/local-runtime/overview-preflight-result.json`에 기존 소스의 실서버 응답과 실제 첨부 실패 기록이 있다. `/models`에는 local-agent-main, `/model/info`에는 같은 별칭의 max_input_tokens=32768이 실제 존재한다. 첫 첨부 36은 .hwp 이름/HWPX bytes 불일치, 둘째 첨부 57은 rhwp conversion_required. 키와 원문은 Git에 저장하지 않는다.

## 문서 준비의 환경 차단

2026-10-09 직접 진단으로 notice 40 HWP는 rhwp export 자체 exit 0, 제품 자원 제한 환경에서는 Rosetta mmap 오류 exit -5임을 확인했다. 보안 제한을 해제하거나 진단 산출물로 적재를 우회하지 않는다. `docs/tracking/findings.md`에 재현 입력·영향·후속 방향을 기록했다. 이번 연결 수정은 실제 모델 metadata와 승인된 합성 JSON 요청까지만 독립 검증 가능하며, 원래 요청의 실제 첨부 기반 개요 완료는 이 문제 해결 뒤 재개한다.

## Local renderer continuation (2026-10-09)

User requested continuation through actual document preparation and overview. Isolation diagnosis on the saved original HWP: individual AS/CPU/FSIZE/NOFILE/CORE limits pass; DATA 512 and 640 MiB fail with Rosetta mmap exit -5; DATA 768 MiB plus AS 32 GiB passes native export with both verification flags. Runtime facts: Linux x86_64, Rosetta in /proc/self/maps, only lo network interface, CapEff=0, NoNewPrivs=1, cgroup memory.max=1073741824, pids.max=128.

1. STEP-R01 [complex]: add trusted worker-only opt-in `BIDOPS_DOCUMENT_EMULATION_PROFILE=rosetta`. Default remains DATA 512 MiB and all existing limits. Opt-in DATA 768 MiB permitted only after checking Linux x86_64, Rosetta process maps, current cgroup v2 memory cap positive and <=1 GiB, pids cap positive and <=128, only loopback network interface, CapEff zero and NoNewPrivs one. Reject malformed/missing evidence and unknown profile before invoking converter; safe `converter_unavailable` without paths or source data. No request option, no generic arbitrary size override, no network/credentials in the document worker. Keep AS 32 GiB, CPU 60s, file cap, fds and core limits unchanged. Unit tests: default, valid profile, each isolation failure, malformed profile, enforced resource values. Leader runs tests. This is an explicit local emulation allowance, not a claim that the 512 MiB child DATA cap is unchanged.
2. STEP-R02 [complex]: independent delta review, local image and opt-in document-worker only, real existing HWP verification under full guarded profile. Preserve failed AttachmentFetch rows; obtain an unprocessed sample through normal worker FIFO, bounded one-shot acquisition, document preparation and immutable snapshot. Do not reset failures or replace original bytes.
3. STEP-R03: show actual public document/page payload to user and obtain per-run approval before one-shot overview. Keep always-on/background models disabled. Record deterministic/semantic validation and screen result, including failures. No main commit/merge/push in this continuation.

Targeted acquisition refinement: STEP-R01b [complex] adds optional `--notice-id` to the existing attachment worker's `--once` CLI and optional notice_id narrowing to its run_once/claim_next seam. Default FIFO, lock/lease/fence/retry behavior is unchanged. No row reset or raw SQL updates. Select only eligible queued/expired records owned by that notice; an empty target does no work. Validate positive id before I/O. Tests cover target isolation (earlier foreign queue entries untouched), empty target, default FIFO, and invalid id. This permits one representative document without processing the entire 264-entry queue.


STEP-R02 result: notice 179 / attachment 264 fetched and structured through the real PostgreSQL/MinIO/ClamAV/scratch worker path. Exactly one of 264 queue rows changed; prior failed rows and 263 other rows are unchanged. PDF export then failed with allocation failure (native exit -6); no overview/model request was made. Guarded Rosetta export-HWPX success is not PDF-rendering proof. New profile tests: 28 passed. Combined Linux document/attachment tests: 181 passed, 2 failed (font shell fixture and HWP acquisition fixture); retain failures, do not report suite green. The HWP acquisition fixture succeeds when run separately; test-process/environment dependency is unresolved.

STEP-R02a [complex]: build local native ARM document-worker from the same pinned rhwp upstream commit cac9b4f7cc743535cd7c00fe4f286abd67e7145b with locked dependencies. Keep repository vendored binary unchanged; local-only image, no credentials/network, existing cgroup/CPU/file/process limits and default DATA512MiB. Record source/binary/image provenance; independent review of local build/Compose delta and leader tests before real snapshot. No broader memory-cap increase.


STEP-R02a result: native ARM binary built from the exact pinned commit; real notice179 PDF conversion succeeded at the unchanged DATA512MiB cap. Rosetta product code/tests and operations opt-in were removed (experimental patch retained only in ignored local evidence). Final native image38bdf390... was applied to both credential-free, network-none,1GiB,pids128,cap-dropALL workers. Real ClamAV→scratch conversion→PostgreSQL/versionedMinIO snapshot path succeeded:80PDF pages, immutable source/PDF/page-text bindings in target179-document.json. Ready bundle was confirmed via existing audited REST.

Tests: native ARM initial run154passed/1failed due stale AMD64 vendor checksum entry in the derived image; image-only packaging fix preserved the original manifest and changed exactly the rhwp row. Targeted manifest test1passed; unchanged154case evidence reused. Final relevant155cases pass, no skips. Prior model231cases are unchanged and reused.

Visual check: physical4matches selected text. Physical5has website details in its text layer/exported text that are not visible in the rendered page; do not send this page. Preview restricted to physical4(779chars), exact draft request conservative total24942/32768tokens including output reserve. Actual model approval was requested for one run(max3calls); the approved execution result is recorded below. No main commit/merge/push.


STEP-R03 result (2026-10-09): user explicitly approved physical page4 only (779chars), one run, at most3calls. Run ff144ffa-7495-4672-99ae-7a2e27a67c1d completed at03:56:41UTC using2calls (draft+semantic), no retry run. All8claims passed deterministic quote and semantic checks; leader independently matched every quote and character offset against the approved page4 text. Budget77,000,000KRW VAT included and period12months(2027.1.1–2027.12.31) match the source. Four quantity warning codes remain preserved under the existing MVP nonblocking-warning contract; passed does not mean warning-free or measured quality. quality_status remains unmeasured_reference. No company fit, deep review or policy activation.

Live UI verification at1280x800 and1440x900 shows the overview, budget/period, page4 evidence links and reference/unmeasured marker; screenshots inspected directly. No page errors or HTTP errors. Initial browser assertion incorrectly expected exactly2 identical text nodes; corrected to assert displayed content without assuming DOM duplication. One WorkJob is completed, global overview/deep-auto-start flags remain false, one-off worker exited0. Evidence: target179-overview-result.json, target179-browser-result.json, target179-runtime-after.json and viewport PNGs.

Remaining: page5 renderer/text-layer discrepancy still excludes that page; full80page visual/quality validation was not performed. Original DEMO-00 notice1489 proof remains blocked and is not replaced by notice179. Product code and independent review inputs are unchanged since the passed delta review; this completion updates execution evidence only.
