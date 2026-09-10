# rhwp R3 저장·snapshot 검증 — 2026-09-10

기준선은 R2를 병합한 main `1db6986`이다. R3는
`/home/jechoi/orca/workspaces/bidops/rdp-r3-snapshot`,
`feat/rdp-r3-snapshot`에서 직접 구현했다. 운영 DB migration·배포·활성화·모델 호출은
수행하지 않았다. 이 기록은 저장 경계의 검증이며 모델 품질 근거가 아니다.

## 구현과 제한

- `0023_rhwp_snapshot`: 기존 snapshot에 nullable HWPX·구조·대응표 참조와 native
  provenance, attempt에 nullable `validation_warnings`를 추가했다. 과거 행은
  바꾸지 않는다. runtime head도 0023으로 맞춰 이전 DB의 앱 시작을 거부한다.
- scratch v2 native sidecar를 UUID 고정 파일로 원자 발행하고, descriptor의
  byte count·hash와 구조·페이지·HWPX 검증 결과를 소비 시 재검증한다.
- 원본·PDF·페이지 텍스트·HWP 변환본·구조·대응표를 exact object version에 묶는다.
  저장과 cache hit 모두 bytes·version·etag·size·hash를 검증한다. native page text는
  구조 블록에서 다시 만들지 않는다. 변환 HWPX는 `source` namespace다.
- native renderer JSON 전체의 canonical hash와 기존 font/config digest를 캐시
  identity로 쓴다. 안전 converter 코드는 실패 attempt와 감사 metadata에 남긴다.
- 같은 문서 버전의 구조 UNIQUE는 유지한다. 기존 원본·MIME·pages·blocks가 같을
  때만 재사용하고 다르면 `structure_binding_mismatch`로 거부한다. 합성 충돌 검사로
  기존 구조·snapshot 보존을 확인했다. [제한과 후속](../tracking/findings.md)을 따른다.
- 새 경고 열은 WP-3 연결을 위한 저장 자리다. R4 소비자·UI, P1 병합, R5 제거는
  이 검증에 포함하지 않았다.

## 관련 테스트

전체 backend·frontend suite와 이미지 재빌드는 하지 않았다. 표의 실행끼리는
중복 검사가 있으므로 개수를 합산하지 않는다.

| 범위 | 결과 |
|---|---|
| 기존 scratch·v4 preparation·runner·ops | 29 passed |
| native scratch/저장/변조/캐시/오류 초기 검사 | 26 passed |
| document_mcp·native 저장·scratch·기존 preparation | 112 passed |
| PostgreSQL R3/기존 v4, module boundaries, runtime privileges | 50 passed |
| 최종 native 저장 검사·scratch·preparation·첨부 취득 materialization 회귀 | 107 passed, 기존 Pydantic `schema` 필드 경고 3개 |
| 저장 경계 보정 후 PostgreSQL native HWP/HWPX roundtrip·worker INSERT·불변성 | 2 passed |
| runtime head 보정 후 0022→0023 기존 행 보존/역이관/시작 거부, fresh head, single head, revision 폭 | 4 passed |

native 집중 검사는 누락·bytes 변조·version 교체·경로 이탈·symlink·페이지 텍스트
해시 불일치·HWPX 검증 실패·부분 publish 정리·추가 metadata 거부·renderer/font 불일치·
최초 저장 시 기본 세 객체 변조 거부를 포함한다. 마지막 107건 명령은 다음과 같다.

```bash
cd web/backend
BIDOPS_DATABASE_URL=sqlite:// BIDOPS_ROOT="$PWD/../.." \
  /home/jechoi/projects/bidops/web/backend/.venv/bin/python -m pytest \
  tests/deep_review/test_rhwp_snapshot.py \
  tests/deep_review/test_document_worker_protocol.py \
  tests/deep_review/test_prespec_v4_preparation.py \
  tests/app/test_prespec_attachment_fetch.py -q --tb=short
```

PostgreSQL 검사는 `tests.postgres.temporary_postgres_server()`의 임시 PostgreSQL
17.11을 만들고 `BIDOPS_TEST_POSTGRES_URL`을 pytest 자식 프로세스에만 전달했다.
pytest harness가 별도 임시 DB를 migration하고 종료 때 제거했다. 실제 권한 파일을
적용해 worker의 snapshot INSERT·경고 column UPDATE, snapshot UPDATE/DELETE 거부를
확인했다. 새 경고를 허용 상태 전이에 저장한 뒤 terminal 수정도 거부했다.

## 실제 native 이미지 왕복

[재현 스크립트](../../scripts/validation/rhwp_r3_probe.py)는 host의 scratch producer와
격리 native worker, 임시 PostgreSQL, versioned filesystem object-store test double을
연결한다. scanner는 명시적인 test double이며 새 ClamAV clean 증거를 주장하지 않는다.
운영 MinIO·ClamAV 인수는 R6에 남긴다.

이미지 `bidops-rdp-r0:20260910`의 ID는
`sha256:84f5cd7f2fff935f4d3502c092607ad3a796e494a47041e976369d3ad249655e`다.
worker는 `network=none`, UID/GID 1000, memory 1 GiB, pids 128, cap-drop ALL,
no-new-privileges로 실행했다. 코드만 read-only bind하고 요청별 scratch만 쓰도록 했다.
새 이미지를 빌드하거나 운영 worker를 재생성하지 않았다.

```bash
/home/jechoi/projects/bidops/web/backend/.venv/bin/python \
  scripts/validation/rhwp_r3_probe.py \
  --input-dir /tmp/bidops-rhwp-r0-task38/input \
  --output docs/validation-runs/2026-09-10-rhwp-r3-snapshot.metrics.json
```

| 표본 | PDF 쪽수 | 준비 시간 | HWPX 검증 | 캐시·scratch |
|---|---:|---:|---|---|
| notice 142 HWPX | 79 | 25.042초 | 원본 그대로, 별도 변환본 없음 | 같은 snapshot 재사용, 파일 정리 |
| notice 10 제안요청서 HWP | 53 | 19.476초 | diff 0, 전후 53쪽 동일 | 같은 snapshot 재사용, 파일 정리 |
| notice 10 과업지시서 HWP | 31 | 11.974초 | diff 0, 전후 31쪽 동일 | 같은 snapshot 재사용, 파일 정리 |

세 표본의 원문 해시는 실행 전후 같고, 대응표 해시는 R2 지표와 모두 같다.
실측 뒤 최초 freeze에서 기본 source·PDF·page-text도 다시 읽도록 검증을 강화했고,
해당 변조 검사와 PostgreSQL HWP/HWPX 왕복만 다시 실행했다. 변환기와 실측을
불필요하게 반복하지 않았다. 전체 안전 지표는
[metrics JSON](2026-09-10-rhwp-r3-snapshot.metrics.json)에 있다.
