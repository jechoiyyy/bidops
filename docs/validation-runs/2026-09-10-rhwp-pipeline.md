# rhwp 문서 변환 파이프라인 R6 운영 인수 — 2026-09-10

작업: [docs/rhwp-document-pipeline/Plan.md](../rhwp-document-pipeline/Plan.md) R6. 담당: 관리자 직접 실행(사용자 요청).
기준 코드: main `8f863da` + 이 기록과 함께 올린 `web/Dockerfile` `fontconfig` 보정. 모델 호출·attempt enqueue·정책 활성화·사람 결정 변경은 없다.

## 결과 요약

| 단계 | 결과 |
|---|---|
| 백업 | DB dump `backups/postgres/full/bidops-before-rdp-r6-20260910T054415Z.dump`(22,511,906 B, SHA-256 `481c9974…7958432`, catalog 1,058, revision `0022`, audit_event 465행)과 manifest. 객체 백업 `backups/objects/20260910T054114Z/`(960 version, source 303·structure 289·quarantine 291·model-response 77, 857 MB, `object-versions.tsv` SHA-256 `4bce1bb4…4569736`, 행마다 stored-byte hash 대조) |
| R5 회귀 발견·보정 | `bidops-rdp-r5:20260910`에는 `fc-list`가 없다(`fontconfig`는 Chromium 의존성으로만 들어왔었다). 격리 실행에서 142가 26.8초 뒤 `converter_unavailable`("PDF 글꼴 manifest를 확인할 수 없습니다"). `web/Dockerfile`에 `fontconfig`를 명시하고 `test_runtime_contract.py`의 폰트 단언을 갱신했다 |
| 이미지 | `bidops-rdp-r6:20260910`(main 트리 + 보정, ID `dde4a0b1…`). `fc-list` 있음, chromium·nodejs 없음, rhwp v0.8.6 `c8268497…`, processor.py `39a8aac5…` |
| 격리 실측(R6 이미지, pids 128·1 GiB·network none) | 142: 21.3초, 79쪽, PDF 4,829,134 B SHA-256 `aee7e648…`(R3 실측과 동일), 구조 pages·blocks(1·2,561)가 기존 `hwpx-stdlib` 구조와 **동일**. 35: 14.4초, 46쪽, blocks 1,454 ≠ 기존 `hwp-rhwp-hwpx` 구조 1,349(차이 구간 64). 59: 9.4초, 84쪽, `source-pdf`, `processor_sha256` `39a8aac5…` |
| migration | `0022_prespec_v4_attempt → 0023_rhwp_snapshot` + `runtime-privileges.sql`. 새 열 10개·`validation_warnings` 확인, snapshot/target/attempt/structure 3·3·7·165행 불변, `prespec_v4_pdf_snapshot` 권한 app·worker `INSERT,SELECT`, `db.migration 0023` 감사 1행 |
| 재생성 | web: `~/.local/state/bidops/deployments/rdp-r6-20260910-4c9f33ec/deploy.compose.json`(직전 배포 복사, image만 교체), healthy, 런타임 `ALEMBIC_HEAD=0023`. document-worker 2개: R6 이미지, `PidsLimit=128`, 1 GiB, `network_mode none`, `cap_drop ALL`, `no-new-privileges`, `/scratch` |
| 표본 준비 | activation `d73daa62…`(explicit_sample, Luna reference-only binding `692b50e4…`, artifact `a6fcf503…`) → 142 31초 `ready`, 59 21초 `ready` → off `5016643f…`. **35는 준비하지 않았다**(아래) |
| API | `overview-pages` 35/59/142 응답이 준비 전후 byte 동일. 142 구조 `22541eb7…` segments 77건 = `mapped` 35·`partial` 42(이전 전부 `unavailable`), `GET /api/document-structures/22541eb7…/pdf` 200 `application/pdf` 4,829,134 B(SHA-256 일치). 35·59 구조는 대응표 snapshot이 없어 segments `unavailable`·PDF 404 `not_found` |
| UI(18887) | 1280×800·1440×900에서 `/pre-specs/35`(PDF 링크 64, 개요 검토 완료)·`/pre-specs/59`(PDF 링크 14, 개요 검토 완료·사람 확인 필요)·`/pre-specs/142`(개요 검토 실패, 링크 0)·`/deep-reviews` 렌더. 가로 넘침·page error·5xx 없음. 35/59 PDF 링크 GET 200 `application/pdf` |

## 새 행

| notice | snapshot | target |
|---|---|---|
| 142 | `f8a42b74-8710-4cc8-90f0-9ca8ae4ed3f1` `generated`, 79쪽, PDF `aee7e648…` 4,829,134 B, `rhwp-svg-pdf` 0.8.6, structure `22541eb7…`(기존 재사용, 새 구조 없음), para-page-map `38958774…`, HWPX sidecar 없음(원본이 HWPX), config `cb73f7a1…` | `f7c73503-8f70-47d4-a309-c9fbd9cfd122` `ready`, `heading_scope`, 4~12쪽, 18,219 B |
| 59 | `3aa6c47f-cd73-49dc-945c-c0c835fd4b98` `original`, 84쪽, 원본 PDF 재사용, `processor_sha256` 변경으로 새 renderer digest | `ec040093-227e-4708-a9ed-b7889cf901d0` `ready`, `heading_scope`, 3~5쪽, 5,814 B(2026-09-08 target과 같은 범위) |

새 객체 6개: 142 `pdf-…`(source)·`para-page-map-…`·`page-text-…`·`manifest-…`(structure), 59 `page-text-…`·`manifest-…`(structure). 감사 2행(active/off). attempt 0건. `/scratch` 작업 디렉터리(inbox·claimed·native·pdf·results)는 비었다.

## 하지 않은 것과 이유

- **35 native snapshot**: native rhwp 0.8.6이 만든 구조의 blocks(1,454)가 기존 구조(WASM rhwp 유래 1,349)와 달라 `_persist_native_artifacts`가 `structure_binding_mismatch`로 거부한다. 실행하면 notice 범위 실패 attempt가 append돼 35의 `current`(completed Luna reference)가 실패로 바뀌므로 실행하지 않았다. 해소는 [findings "같은 문서 버전의 native 구조가 기존 구조와 다르면"](../tracking/findings.md)대로 구조 revision 설계·승인이 필요하다.
- **attempt**: overview endpoint(`192.168.0.139:58765`)가 여전히 닿지 않아 enqueue하지 않았다. 142의 `current`는 기존 실패 attempt `dbbc7b5f…`로 남는다(ready target 미표시 finding, Plan §6).
- **심층 검토 화면의 segment PDF 링크**: 운영 DB에 `deep_review` 행이 0건이어서 실제 화면은 확인하지 못했다. REST(`segments`·`/pdf`)로만 확인했고 화면 계약은 R4 fixture spec에 의존한다.
- 기존 실패 4건(autogenerate drift·닫힌 테이블 82≠81·mapper isolation·`common-interactions:211`)은 건드리지 않았다.

## 재현 명령

```bash
# 백업
docker exec -i bidops-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/postgres/full/<dump>
docker build -f web/Ops.Dockerfile -t bidops-ops:20260910 .
docker run --rm --network bidops_storage --user "$(id -u):$(id -g)" -e HOME=/tmp -e MC_CONFIG_DIR=/tmp/mc \
  --env-file <BIDOPS_MINIO_ROOT_USER/PASSWORD 두 줄> -v "$PWD/backups/objects/<stamp>:/backup/objects" --entrypoint bash bidops-ops:20260910 \
  -c 'mc alias set bidops http://minio:9000 "$BIDOPS_MINIO_ROOT_USER" "$BIDOPS_MINIO_ROOT_PASSWORD" >/dev/null && MINIO_ALIAS=bidops OBJECT_BACKUP_DIR=/backup/objects bash /opt/bidops/scripts/backup-objects.sh'

# 이미지·격리 실측(Plan §3 probe 형태, R6 이미지)
docker build -f web/Dockerfile -t bidops-rdp-r6:20260910 .
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 --cap-drop=ALL --security-opt no-new-privileges \
  -v "$PWD:/app:ro" -v "$IN:/input:ro" -v "$OUT:/out:rw" -v "$PROBE:/probe.py:ro" --workdir /app/web/backend \
  --entrypoint /usr/local/bin/python bidops-rdp-r6:20260910 /probe.py 142.hwpx application/hwp+zip

# migration (compose run은 --no-build가 없어 --pull never로 이미지 고정 overlay를 쓴다)
OVERLAY='{"services":{"document-worker":{"image":"bidops-rdp-r6:20260910"},"migrate":{"image":"bidops-rdp-r6:20260910"}}}'
docker compose --env-file .env -p bidops -f docker-compose.yml -f overlay.json run --rm --no-deps --pull never migrate
COMPOSE_PROJECT_NAME=bidops docker compose -p bidops -f ~/.local/state/bidops/deployments/rdp-r6-20260910-4c9f33ec/deploy.compose.json up -d web
docker compose --env-file .env -p bidops -f docker-compose.yml -f overlay.json up -d --no-deps --no-build --force-recreate document-worker

# 준비 (web 컨테이너 app role, binding은 2026-09-08 Luna reference-only 감사에서 복원)
docker exec bidops-web-1 python -m app.deep_review.cli prespec-v4 --activate --actor jechoi --mode explicit_sample \
  --artifact /app/web/backend/app/deep_review/policies/prespec-v4-activation-v1.json --binding /tmp/v4/binding.json
docker exec bidops-web-1 python -m app.deep_review.cli prespec-v4 --prepare --actor jechoi --mode explicit_sample --notice-id 142 \
  --renderer /tmp/v4/renderer-native.json --font /tmp/v4/font-native.json --config /tmp/v4/config.json --options /tmp/v4/options.json
docker exec bidops-web-1 python -m app.deep_review.cli prespec-v4 --prepare --actor jechoi --mode explicit_sample --notice-id 59 \
  --renderer /tmp/v4/renderer-source-pdf.json --font /tmp/v4/font-source-pdf.json --config /tmp/v4/config.json --options /tmp/v4/options.json
docker exec bidops-web-1 python -m app.deep_review.cli prespec-v4 --deactivate --actor jechoi --reason rdp_r6_native_snapshots_prepared_142_59_activation_restored_off
```

binding JSON: native renderer는 `validate_native_renderer`의 7개 키(`renderer=rhwp-svg-pdf`, `rhwp_version=0.8.6`, `rhwp_binary_sha256`, `backend=svg`, `compat=2022`, fallback 폰트 3종, `worker_image_digest=null`), 폰트는 `{"font_manifest_sha256": "92e5dc4f…1650a9", "worker_image_digest": null}`(R6 이미지 실측값, R3 이미지와 같음). 원본 PDF는 `{"source_pdf": true, "processor_provenance": {...}}`·`{"source_pdf": true, "font_provenance": null}`. config는 `{"options": vars(ProcessorOptions.from_mapping(options))}`이며 `renderer` 필드를 포함한다. 값은 [metrics](2026-09-10-rhwp-pipeline.metrics.json)에 있다.
