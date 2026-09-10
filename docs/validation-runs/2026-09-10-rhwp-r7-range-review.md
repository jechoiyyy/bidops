# rhwp 문서 변환 파이프라인 R7 범위 선택 보조 — 2026-09-10

작업: [Plan.md](../rhwp-document-pipeline/Plan.md) R7. 사용자 승인("R7까지 완료") 뒤 Opus 서브에이전트 3개(WP-A 산출물·WP-B 선택기/REST/CLI·WP-C 화면)에 위임하고 관리자가 diff·게이트를 검수해 main에 병합했다(`a0a2039`, `1f66044`). 모델 호출·attempt·정책 활성화는 없다.

## 구현 요약

| 구성 | 내용 |
|---|---|
| 산출물 ⑦ | worker가 rhwp `digest <입력> --sections --json`을 다섯 번째 호출로 실행해 `bidops.section-candidates.v1`(`index`·`title`(공백 정규화, 300자 cap)·`page`(1 기준)·`char_count`·`truncated`, `mode clause|page`)을 만든다. `excerpt`·`nextStep`·`source`·`untrusted*`는 버린다. 형식 위반은 안전 코드 `section_candidates_invalid`(Spec §5). v2 protocol sidecar `section-candidates.json`(hash 결속), 객체 `structure/prespec-v4/{document}/section-candidates-{sha}.json` |
| 0024 | `prespec_v4_pdf_snapshot`에 nullable `section_candidates_content_object_id`·`_location_id`·`_sha256`(FK RESTRICT). 셋 다 null인 R6 snapshot은 `binding_sha256`이 바뀌지 않아 캐시 재사용이 유지된다 |
| 선택기 연결 | `select_v4_input_range`가 `ready`가 아니면 실패 attempt 대신 검토 manifest `bidops.prespec-v4-range-review.v1`을 저장하고 `needs_human_review` target(`heading_scope`)을 동결한다. `--enqueue`에서도 attempt 없음 |
| 사람 확정 | `POST /api/pre-specs/{id}/overview-pages/range-confirmations`(actor 헤더 필수, 절 index 쌍 또는 쪽 쌍) → 같은 snapshot에 `human_confirmed`·`ready` target과 감사 `prespec_v4.range_confirmed`. `attempt_enqueued`는 항상 `false`. `GET …/overview-pages`에 `range_review` 투영 |
| LLM 보조 | `prespec-v4 --assist-range --target-id --actor`만. 참조 모드·최신 확정 대기 target·후보 ≥2·target당 1회, `resolve_model_endpoint("overview")` fail-closed. 결과는 감사 `prespec_v4.range_assist`(index·hash만)이고 target·attempt를 만들지 않는다 |
| 화면 | 사전규격 상세 "현재 판단"에 `개요 범위 확인` 카드. 후보 표(시작/끝 radio)·후보 없으면 쪽 입력·모델 제안은 미리 고르기만·담당자 이름 뒤 `범위 확정`. 확정 상태는 읽기 전용 요약 |

## 게이트

| 검사 | 결과 |
|---|---|
| 백엔드(통합 트리, 닿는 파일 12개 1회) | `test_document_mcp`·`test_document_worker_protocol`·`test_prespec_v4_preparation`·`test_prespec_v4_ops`·`test_page_overview`·`test_rhwp_snapshot`·`test_prespec_v4_runner`·`test_module_cli_entrypoints`·`test_runtime_contract`·`test_module_boundaries`·`test_module_public_surface`·`test_deep_reviews` = **319 passed** |
| PostgreSQL(WP-A 브랜치, R3 방식 임시 17 서버) | `test_rhwp_snapshot_postgres.py` 5 passed(0024 열·FK·감사·downgrade 거부), `test_db_migrations`·`test_revision_migrations`·`test_runtime_database_privileges` 51 passed. 병합 트리의 해당 파일은 동일해 반복하지 않았다 |
| 프론트(통합 트리) | `tsc -b`·production build 통과, `page-overview.spec.ts --project=app` **9 passed**(기존 6 + 신규 3: 대기 렌더·POST 본문/actor 헤더·쪽 모드·확정 요약) |
| 이미지 `bidops-rdp-r7:20260910` | `fc-list` 있음, chromium·node 없음, `ALEMBIC_HEAD=0024_section_candidates`. 격리 실측(142, pids 128·1 GiB): 24.1초, 79쪽, PDF SHA-256 `aee7e648…`(R3·R6과 동일), blocks 2,561, **후보 43절 `clause`**, 첫 세 후보 page 25, 산출물 9,775 B |
| 자동 실행 열지 않음 | 확정 POST와 `--assist-range`는 attempt를 만들지 않는다(테스트 고정). 운영 확인: 존재하지 않는 target → 404 `target_not_found`, actor 없음 → 400, R6의 ready target `f7c73503…` → 409 `target_not_pending`(target·감사 행 수 불변 5·467) |

## 운영 반영(2026-09-10)

- 백업: `backups/postgres/full/bidops-before-rdp-r7-20260910T065315Z.dump`(revision 0023, 22,527,138 B, SHA-256 `bc699ea6…`, manifest 포함). 객체는 R6 manifest 이후 R6 산출물 6개만 추가돼 재백업하지 않았다.
- `0023 → 0024_section_candidates` 적용(이미지 고정 overlay, `run --rm --no-deps --pull never migrate`), 권한 재적용. snapshot·target·attempt·audit 5·5·7·467 불변, 후보 참조 있는 snapshot 0건.
- web(배포 dir `~/.local/state/bidops/deployments/rdp-r7-20260910-cf89169f`)·document-worker 2개(pids 128·network none)를 `bidops-rdp-r7:20260910`로 재생성.
- API: `overview-pages` 35/59/142는 `range_review: null`이 추가된 것 외에 R6 응답과 byte 동일. 142 segments·구조 PDF(4,829,134 B) 동일. `--assist-range` 배선은 target_not_found/target_not_pending로 확인(모델 호출 없음). 두 폭 UI 재확인 통과(넘침·오류 없음).

## 하지 않은 것과 한계

- **실표본의 사람 확정 흐름은 운영에서 재현하지 못했다.** 표본 3건 모두 heading 선택기가 `ready`라 `needs_human_review` target이 없다. 흐름은 API 종단 테스트(`test_page_overview`·`test_prespec_v4_ops`)와 Playwright 목 검사로만 확인했다. 실제 확정 대기 문서가 들어오면 `docs/operations.md`의 절차로 확인한다.
- 실제 모델 보조 호출 없음(endpoint 미복구). 원응답 raw는 저장하지 않고 hash만 감사에 남긴다(참조를 소유할 행이 없어 고아 암호화 객체를 피함).
- `complete_structured`가 승인 generation의 temperature 0.7을 고정 전송해 보조 호출에 temperature 0을 주지 못한다(재시도 0·seed 0·strict schema로 대신). `needs_human_review` target에는 검토 manifest 객체가 있으나 `manifest_content_object_id`가 결속되지 않는다(`freeze_v4_target`이 non-ready manifest 참조를 거부). 둘 다 [findings](../tracking/findings.md)에 기록.
- 기존 R6 snapshot에는 후보가 없다. 142/59에 후보를 붙이려면 config나 renderer가 바뀌지 않는 한 새 snapshot이 만들어지지 않으므로, 후보는 다음 표본부터 생긴다.

## 재현 명령

```bash
# 격리 실측(후보 포함)
docker run --rm --network none --user 1000:1000 --memory 1g --pids-limit 128 --cap-drop=ALL --security-opt no-new-privileges \
  -v "$PWD:/app:ro" -v "$IN:/input:ro" -v "$OUT:/out:rw" -v "$PROBE:/probe.py:ro" --workdir /app/web/backend \
  --entrypoint /usr/local/bin/python bidops-rdp-r7:20260910 /probe.py 142.hwpx application/hwp+zip
# 게이트
cd web/backend && .venv/bin/python -m pytest tests/deep_review/test_document_mcp.py tests/deep_review/test_document_worker_protocol.py \
  tests/deep_review/test_prespec_v4_preparation.py tests/deep_review/test_prespec_v4_ops.py tests/deep_review/test_page_overview.py \
  tests/deep_review/test_rhwp_snapshot.py tests/deep_review/test_prespec_v4_runner.py tests/app/test_module_cli_entrypoints.py \
  tests/app/test_runtime_contract.py tests/app/test_module_boundaries.py tests/app/test_module_public_surface.py tests/app/test_deep_reviews.py -q
cd web/frontend && npx tsc -b && npm run build && npx playwright test tests/page-overview.spec.ts --project=app
# 운영
docker compose --env-file .env -p bidops -f docker-compose.yml -f overlay-r7.json run --rm --no-deps --pull never migrate
COMPOSE_PROJECT_NAME=bidops docker compose -p bidops -f ~/.local/state/bidops/deployments/rdp-r7-20260910-cf89169f/deploy.compose.json up -d web
docker compose --env-file .env -p bidops -f docker-compose.yml -f overlay-r7.json up -d --no-deps --no-build --force-recreate document-worker
# 사람 확정(확정 대기 target이 있을 때)
curl -X POST -H 'Content-Type: application/json' -H 'X-BidOps-Actor-Name: <담당자>' \
  -d '{"target_id":"<uuid>","start_index":3,"end_index":7,"first_page":null,"last_page":null,"note":null}' \
  http://127.0.0.1:18887/api/pre-specs/<notice>/overview-pages/range-confirmations
docker exec bidops-web-1 python -m app.deep_review.cli prespec-v4 --assist-range --target-id <uuid> --actor <표식>
```
