# 사전규격 개요 검토 Mac 운영 실행 — 2026-10-15

결정: [ADR-0072 추가 결정](../../tracking/decisions/0072-c2-mac-litellm-ollama.md). 사람 결정(jechoi):
사전규격을 **개요 검토까지만** 진행(일괄 승인), 이어서 개요 대상을 **등록일 10-13·10-14**로 축소.
결과는 전부 `quality_status=unmeasured_reference`이며 품질 근거·운영 완료 근거가 아니다.

## 배포

| 항목 | 값 |
|---|---|
| checkout | `/Users/temp/orca/bidops-c2mac`, 브랜치 `feat/c2-litellm-mac`(미커밋) |
| 백업 | `backups/postgres/full/bidops-20261014T230746Z.dump` sha256 `35c81181…`, `pg_restore --list` 1,131줄 |
| 이미지 | `bidops:c2mac-20261015`(amd64, 롤백 `c2mac-20261014b`), 문서 worker `bidops:document-arm64-c2mac-20261015`(rhwp `c32c7cb2…`, 앱 manifest `8821d56c…`) |
| 개요 모델 | LiteLLM `local-agent-main`, revision `41a558fc…`, 문맥 32768 — identity 확인(completion 없음) |
| 개요 정책 | `prespec-overview-policy-v7-litellm-v2.json` `0e69ae43…` (900초·8192·lease 3060) |
| 꺼 둔 것 | 심층 자동 시작, 회사 핏, active profile/policy ID, C-1 판정, 상시 첨부 worker(아래). 실행 뒤 개요 플래그도 끔(web·analysis-worker 재생성, 컨테이너 env `false` 확인) |

## 수집·적재

`run-daily-lifecycle.sh --track notices --from-date 2026-10-07 --to-date 2026-10-14`(cron과 같은 env,
`flock`·`timeout 4h`) exit 0. 8회차 모두 complete. 적재 경고는 회차당 113~292건이며 전부 비차단
(`opportunity_link_target_missing` — 연결 발주계획이 이 DB에 없음, `screening_results_missing` 1건 —
C-1 미실행). SW 사전규격 427건, 첨부 561개.

## 개요 대상 10-13·10-14 (151건)

상시 첨부 worker를 멈추고 대상 공고만 [`prespec_target_driver.py`](prespec_target_driver.py)(첨부 worker
컨테이너, `run_once(notice_id=…)`)로 받았다. 자동 준비·개요 등록은 [`prespec_prepare_loop.py`](prespec_prepare_loop.py)
(web 컨테이너, `prepare-overviews`와 같은 `maybe_auto_prepare` + `session.commit()`)가 했다.
첨부 201개 → `완료` 180, `차단` 21(`unsafe_document` 11·`unsupported_extension` 6·`mime_mismatch` 4).

| 등록일 | 공고 | completed | needs_human_review | input_capacity_exceeded | 기타 실패 | 묶음 ready·개요 대상 아님 | 묶음 draft(차단) | 묶음 없음 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 10-13 | 57 | 30 | 2 | 14 | 0 | 3 | 4 | 4 |
| 10-14 | 94 | 35 | 3 | 22 | 1 | 7 | 18 | 8 |

- `completed`·`needs_human_review` 60건(재시도 run 기준) 평균 139초, 모델 호출 120회,
  2026-10-15 00:29~04:06Z. 자동 범위(대개 2~4쪽)를 잡은 공고는 거의 전부 끝났다.
- `input_capacity_exceeded` 36건: 자동 범위 선택이 실패하면 fallback 1~60쪽이 되고 로컬 문맥
  (입력 상계 약 23.5k byte)을 넘어 **호출 전에** 실패한다. 화면에서 사람이 쪽 범위를 확정하면
  (`POST /api/pre-specs/{id}/overview/range-confirmations`) 다시 돌 수 있다.
- `needs_human_review` 5건은 `semantic_review_failed`. 기타 실패 1건은
  `pdf_preparation_failed:rhwp_manifest_invalid`.
- 개요 대상 아님 10건: `rfp_filename_missing` 6·`ambiguous_rfp_filename` 4(파일명 규칙, 2026-09-17 결정).
- draft 22건은 위험·형식 불일치 첨부가 확정을 막아 사람이 첨부를 제외하거나 올려야 한다.
- 심층 검토 행 0. 대상 밖 공고의 개요 run은 축소 전에 이미 돈 16건(1·4·49·50·64·71·72·74·80 등)뿐이다.

## 관측한 실패와 대응

1. **Rosetta 변환 실패**(23:10~23:15Z): amd64 rhwp가 자식 `RLIMIT_DATA` 512MiB와 충돌해 즉시 종료.
   첨부 worker 정지 → arm64 문서 worker로 교체. 그 사이 `차단` 14건은 되살릴 경로가 없다(findings).
2. **자동 준비 미커밋**: 첨부 worker 경로의 `maybe_auto_prepare`가 savepoint 안에서만 커밋해 묶음이
   사라졌다(findings). web 쪽 준비 루프로 우회.
3. **정책 경로 미렌더**: 첨부 worker 컨테이너에서 준비한 13건이 기본 v7 digest로 들어가
   `binding_mismatch`(호출 전). web에서 다시 준비해 재시도했다.
4. 첫 드라이버를 멈출 때 lease가 남은 첨부 1건(공고 517)은 lease 만료 뒤 `--once`로 다시 받았다.

## 이 기록이 증명하지 않는 것

- 개요 내용의 정확성. 사람 대조·품질 측정을 하지 않았다.
- 10-04~10-12 등록분. 첨부 일부만 받았고(상시 worker 정지 전 약 400개) 개요는 대상이 아니다.
- 첨부 worker 상시 운영. 위 결함 2·3 때문에 상시 worker만으로는 개요까지 가지 않는다.
- host 방화벽 egress 제한. Mac에는 없고 앱 허용 목록(`www.g2b.go.kr`)만 걸었다.
