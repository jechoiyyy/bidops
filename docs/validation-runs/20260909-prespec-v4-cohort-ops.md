# 2026-09-09 v4 cohort/ops focused validation

아래 `최종 운영 상태`가 이 기록의 최신 사실이다. 이어지는 `구현 경계`와
`focused commands`의 운영 DB·MinIO 미사용 문장은 초기 격리 실행 시점의 역사적
기록이며, 후속 실제 표본 실행과 구분한다.

## 최종 운영 상태 (2026-09-09)

위 서두와 focused commands는 운영 적용 전의 격리 실행을 설명한다. 이후 root가
백업 후 0020→0022 migration·runtime grant를 적용하고 명시 표본만 표준 ops 경계로
실행했다. 자동 new-reference, scheduler, 품질 승격, 회사 핏 자동 시작은 계속
비활성이다.

- 개발 HWP notice 35는 target
  `5664dbef-4341-4348-b4f0-da2f6b455168`와 attempt
  `0200ccfd-5b08-42c8-a677-6aa8aa8ca117`가 실제 worker에서 completed 됐고,
  overview result `a28a188b-0638-4dbb-b867-ea5a12c6c168`가 current다.
- 운영 원본 PDF notice 59는 target
  `a188de71-9aaa-46e4-b30e-2fc484e53e82`, app attempt
  `3b82e19d-7939-4d3d-b07a-a02b795b2f80`, worker result
  `04d6182f-f073-450a-b8be-30f141db9f02`가 생성됐고 API `current=completed`를
  확인했다. `prompt_version=v4`, `model=gpt-5.6-luna`,
  `quality_status=unmeasured_reference`로 저장했으며 Luna reference JSON과 API
  payload의 exact 일치를 확인했다. PDF 원본은 passthrough 계약으로 보존했다.
- company-fit 후속은 notice 35에서 attempt
  `bb2d93f4-1915-4e72-a4f5-f647d8860a5e`, `completed/current/unknown`, raw
  SHA-256 `c147828b4efa9423d7af2ac138705e8d775a5a8c674a543275fb35dfc276d822`로
  저장했고 API가 Luna reference 첫 응답과 exact 일치했다. notice 59에서는 attempt
  `4af5b488-59c2-445e-8cf3-4a33baad44be`, `needs_human_review/current`,
  `result=null`, raw SHA-256
  `67b292a7ca012a7995f7a98d7be11d972fd97e72b603cf5e17552cb272254f11`로 남겼다.
  `unsupported_number`는 index 0 선택 근거에 24시간이 없어서 발생했으며 암호화 raw를
  보존하고 보정·재시도하지 않았다.
- 필수 notice 142는 첫 attempt
  `4a8a95e8-e761-4d08-872a-bf619610837c`가 `conversion_required`로 실패했고,
  fsize 경계 수정 worker에서 재시도한 두 번째 attempt
  `db1d063e-9eb9-4d04-bad4-ed14543c23ae`도 `pdf_preparation_failed`로 남았다.
  마지막 2GiB 실행도 job
  `9a8ded11-f357-4847-a534-65be6a0810f8`, attempt
  `954abd8b-e161-457a-9236-464fb47604ba`, duration `300048ms`의 timeout으로
  실패했다. 142는 성공 PDF/snapshot/current 없이 미검증으로 확정했으며, 추가
  변환 진단·대체 테스트는 수행하지 않는다.
- fsize 256MiB 변경은 원인 해결을 입증하지 못해 원복했다. 당시 runtime binding
  digest `5481b74873203aafcced19142e66f1f4aa78acd0d6a50bf72bf43eb68552b6d3`는
  실패 진단 이미지의 기록일 뿐 제품 provenance로 사용하지 않는다. 폐기한
  provenance 주입용 `/tmp/bidops-v4-freeze-artifacts.py.discarded`는 사용하지
  않는다.
- backend controlled runner/current/권한·migration 검증은 `34 passed, 8 baseline
  warnings, skipped 0`, UI focused Playwright는 `6 passed`와 build·TypeScript·
  contrast 통과다. explicit sample activation은 OFF이며 audit
  `07c1d75a-c36a-48c7-9de5-a7efa1e741c7` 사유는
  `reference_samples_complete_with_142_unverified`다. 142·35·59 모두 grade는
  `None`이고 automatic deep는 강제하지 않았으며 사람 결정은 변경하지 않았다.
  실제 API 브라우저/UI는 35/59에서 사업명 검색·목록/상세·독립 상세·refresh/reentry,
  1280×800·1440×900, 본문·제한사항·prompt/result ID·PDF hash/link까지 통과했다.
  35 `unknown` 근거와 59 `needs_human_review` 오류·안전 문구·판정 본문 비노출도
  확인했다. 첫 timeout은 검증 script가 지원하지 않는 `notice_pk` query URL을 사용한
  탓이었고 사업명 검색 경로로 수정 후 통과했으며 제품 코드 결함으로 판정하지 않는다.
  결과는 `.dryforge/prespec-v4-luna-20260909/ui-acceptance-result.json`과 script에
  보존한다. 실제 URL은 `localhost:18887/pre-specs/{35,59}`이며 18787 bind 실패를
  기록한다.
  `overview-actual`은 중지했고 `prespec-actual`은 원래 `sleep infinity`로 복원했다.
  document-worker 두 개는 `bidops-v4-luna-reference:20260909-final`, 1 GiB 조건으로
  복원했다. persistent reference artifacts는
  `.dryforge/prespec-v4-luna-20260909/{overview-generation,company-fit-input-35-59,company-fit-generation-35-59}`에
  두며 credentials를 포함하지 않는다. 이미 통과한 명령은 변경·새 실패 근거 없이
  반복하지 않았다.

## 구현 경계

- `prespec_v4_ops.py`가 별도 registry/table 없이 `AuditEvent`의 최신 activation/off
  행을 읽고, `explicit_sample`과 `new_reference`를 구분한다.
- 활성 binding은 reference-only·`unmeasured_reference`로 고정한다. 기본 이벤트 없음/
  off, policy/binding 불일치, grade/SW/auto-ready bundle/관측 근거 누락은 fail closed다.
- 준비는 기존 `prepare_v4_pdf_snapshot` → full page-text read →
  `select_v4_input_range` → structure manifest → `freeze_v4_target`를 사용한다.
  attachment fetch의 120초 lease나 legacy overview queue를 재사용하지 않는다.
- app role이 prepare/enqueue 때 `WorkJob`과 attempt를 만들고, analysis worker는
  frozen manifest와 attempt state만 읽고 갱신한다. terminal retry는 기존 WorkJob
  aggregate slot을 재사용하면서 새 attempt sequence를 append한다.

## focused commands

```text
cd web/backend
./.venv/bin/pytest -q \
  tests/deep_review/test_prespec_v4_ops.py \
  tests/deep_review/test_prespec_v4_preparation.py \
  tests/deep_review/test_prespec_v4_runner.py \
  tests/app/test_module_cli_entrypoints.py \
  tests/app/test_runtime_database_privileges.py --tb=short
```

결과: 초기 ops focused 묶음은 `32 passed, 2 skipped`였고, worker SELECT 권한 보정
후 static privilege subset은 `2 passed, 9 deselected`였다. 별도로
`test_runtime_database_privileges.py::test_effective_runtime_role_matrix_and_future_defaults`
를 현재 PostgreSQL 17 컨테이너의 임시 database/role로 실행해 `1 passed`를 확인했다.
이 단계에서 변경 없는 기존 묶음은 반복하지 않았다. 문서 compilation과
`prespec_v4_ops.py`, `prespec_v4.py`, `prespec_v4_runner.py`, `prespec_v4` CLI,
새 ops test의 `py_compile`도 통과했다.

ops test가 확인한 계약은 다음과 같다.

1. activation event가 없으면 enqueue가 `v4_disabled`로 중단되고 WorkJob/attempt를
   만들지 않는다. active→deactivate 뒤에도 새 예약은 중단된다.
2. 같은 target의 중복 enqueue는 같은 active attempt를 반환하며, terminal failure는
   기존 attempt를 수정하지 않고 다음 sequence attempt를 만든다.
3. activation 이전 관측은 제외되고, 이후 첨부 metadata fingerprint가 달라진 관측은
   실제 DocumentVersion source hash/size와 결속된 `attachment_change`로 인정된다.
4. 기존 snapshot/config/source binding cache hit는 converter를 재호출하지 않고
   prepare→manifest→enqueue controlled roundtrip을 통과한다.

## 남은 범위 (초기 focused 실행 시점)

고정 표본 142/35/59의 실제 운영 snapshot/manifest 저장, 자동 new-reference 실제
관측 등록, private model 호출, company-fit/deep-review 자동 시작, live API/UI와
운영 배포는 수행하지 않았다. 142/35/59에는 grade가 없어 explicit sample 수동
검증과 automatic priority gate를 혼동하지 않는다. 실제 model endpoint의 현재
연결 실패도 대체 모델이나 추가 harness로 우회하지 않고 미검증으로 남긴다.

## Luna 명시 참조 seam

사용자 명시 Luna 응답은 `/tmp/bidops-v4-luna-reference-43qu7brn/`의
`generation-record.json`과 sample별 고정 input/output JSON으로 확인했다. 기존 v4
policy file SHA, prompt byte/hash, input/output byte/hash, `actualmodel`,
`effort=max`, `opaqueweightsrevision=null`을 검사하는 loader가 세 sample을 통과했다.
세 sample이 하나의 불변 generation record에서 나온 실행임을 결속하기 위해 v4
`model_digest`에는 record 전체의 SHA-256
`9b3b2f5e2571314433347ccfaac1e3821b0dd3a16bd5b93b81306e8fd892489c`를 공통으로
사용한다. 각 sample의 입력·출력·prompt를 묶은 manifest SHA는 audit metadata의
`sample_manifest_sha256`로만 보존한다.

- sample 142 audit manifest: `67cbe1cb363b09c771833e6dc71e1aaf7dd6bdd6a3c60c2570ecdee4b8914e73`
- sample 35 audit manifest: `7397f7a4f3d6c93ad93f3dc496f5b439f46d36cafc89f3584be5ff4c347bc6a2`
- sample 59 audit manifest: `18f7ee33f09a2db81cd5fb1fa52615afc8e8ebc990ca17de62e13fc7289908b1`

재현 명령:

```text
cd web/backend && ./.venv/bin/python - <<'PY'
from pathlib import Path
from app.deep_review.services.prespec_v4_runner import load_v4_policy
from app.deep_review.services.prespec_v4_luna_reference import load_luna_generation_sample
p = load_v4_policy()
for key in ("142", "35", "59"):
    r = load_luna_generation_sample(
        Path("/tmp/bidops-v4-luna-reference-43qu7brn/generation-record.json"),
        sample_key=key, policy=p,
    )
    print(key, r.manifest_sha256, len(r.input_bytes), len(r.prompt_bytes), len(r.raw_response))
PY
```

출력은 세 줄 모두 공통 record digest
`9b3b2f5e2571314433347ccfaac1e3821b0dd3a16bd5b93b81306e8fd892489c`를 사용하며,
크기는 각각 `142 16111/28982/4658`, `35 13073/25944/4988`,
`59 4747/17618/4202`였다.
sample별 audit digest는 위의 `sample_manifest_sha256` 값과 일치했다.

`tests/deep_review/test_prespec_v4_luna_reference.py --tb=short`는 `1 passed`이며,
CLI help/관련 파일 `py_compile`도 통과했다. 아직 DB target에 대한 실제 enqueue,
worker role 실행, API/UI live current 확인은 수행하지 않았다. 정상 소비 명령은
`docs/operations.md`의 app `--enqueue-reference` 후 worker `--run-reference` 두
단계이며, 회사 핏·자동 심층·운영 품질 승격은 이 참조에서 수행하지 않는다.
