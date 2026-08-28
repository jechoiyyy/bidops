# Phase 0–2 실행 계획

2026-08-27 코드 리뷰(`docs/review/2026-08-27-web-review.md`)에서 확인한 세 가지 차단 요인을
순서대로 제거한다. 이 문서는 **무엇을 어떤 순서로** 하는지를 정하고,
각 작업의 정확한 변경 명세는 [spec.md](./spec.md)에 있다.

## 왜 이 순서인가

| 단계 | 목표 | 이걸 안 하면 |
|---|---|---|
| 0 | 문서대로 따라 하면 스택이 뜬다 | 신규 셋업이 첫 명령에서 실패한다. 로컬에 `pip`/`venv`가 없어 도커가 유일한 실행 수단이다 |
| 1 | 실패가 보인다 | 워커가 조용히 죽어도 컨테이너는 healthy로 보인다. 2단계 디버깅이 전부 추측이 된다 |
| 2 | 파이프라인 A가 목표 스택에서 완주한다 | A는 SQLite·단일 공고·compose 밖에서 한 번 성공했을 뿐, PostgreSQL에서는 검증된 적이 없다 |

`0 → 1` 순서는 바꾸지 않는다. 못 띄우는 상태에서 로그를 넣어도 볼 수 없다.

## 작업 단위

각 작업은 codex exec에 위임하고, 완료 후 diff 리뷰 → 수정 → 다음 작업 순으로 진행한다.

| ID | 단계 | 제목 | 주요 대상 |
|---|---|---|---|
| T0 | 0 | 개발 진입점 정합 | `docker-compose.yml`, `.env.example`, `docs/operations.md` |
| T1 | 1 | 구조화 로깅 기반 | `app/redaction.py`(신설), `app/logging_setup.py`(신설), `app/config.py`, `app/main.py`, 워커 2개 |
| T2 | 1 | 침묵 지점 계측 | `workers/analysis.py`, `workers/document.py`, `runtime.py`, `services/scheduler.py`, `screening/queue.py` |
| T3 | 2 | T7 산출물 지속성 | `docker-compose.t7.yml` |
| T4 | 2 | 판정 egress 오버레이 | `docker-compose.t7.screening.yml`(신설), `tests/test_t7_runtime_contract.py` |

의존 관계는 `T0 → T1 → T2`, `T0 → T3 → T4`다. T1/T2와 T3/T4는 서로 독립이지만
검증 편의를 위해 T0→T1→T2→T3→T4 순서로 직렬 실행한다.

## 검증 단계 (위임하지 않음)

| ID | 시점 | 내용 | 통과 기준 |
|---|---|---|---|
| V0 | T0 후 | 루트 compose `config` 파싱, ops profile 서비스 목록 확인 | `web` 서비스가 없고 ops 4개가 남는다 |
| V1 | T2 후 | 백엔드 테스트 전량 | 기존 통과 수 유지 + 신규 로깅 테스트 통과 |
| V2 | T4 후 | t7 스택 기동 → `/api/health` → 로그 확인 | `{"status":"ok"}`, 워커 로그에 구조화 라인이 보인다 |

## 실행 결과 (2026-08-27)

다섯 작업 모두 완료했다. 백엔드 테스트는 기준선 733 → 741 passed이며,
남은 2건은 승인된 profile blob이 이 저장소 이력에 없어서 생기는 환경 아티팩트로
작업 전후가 동일하다.

| ID | 결과 | 검증 |
|---|---|---|
| T0 | 완료 | `docker compose --profile ops config --services`가 ops 4개만 출력 |
| T1 | 완료 | 신규 로깅 테스트 7건 통과 |
| T2 | 완료 | 5개 지점 계측, 제어 흐름 무변경 |
| T3 | 완료 | 기동한 `web`에서 `/app/data`·`/app/reports` 마운트 확인 |
| T4 | 완료 | `web` 컨테이너에서 승인된 Ollama endpoint 도달 확인 (`qwen3.8:27b`) |
| V2 | 통과 | 전체 스택 healthy, `/api/health` = `{"status":"ok"}` |

V2에서 계획에 없던 결함 하나를 발견해 함께 고쳤다. `web/Dockerfile`이 `/scratch`를
만들지 않아 `document-scratch` named volume이 root 소유로 생성되고,
non-root `document-worker` 두 replica가 `PermissionError`로 즉시 종료했다.
Dockerfile의 기존 `install -d` 목록에 `/scratch`를 추가했다.
이 결함은 T2가 넣은 구조화 로그가 드러냈다.

`docs/validation-runs/20260826-t15-phase1-live-retry.md`가 기록한 실제 판정 스모크는
정책·프로필 활성화와 운영자 승인이 선행되어야 하므로 이 계획의 범위 밖이다.
V2는 "스택이 뜨고 관측된다"까지만 확인한다.

## 지켜야 할 경계

- 회차 원본, 기존 리뷰, 정본 DB를 덮어쓰지 않는다.
- 앱 시작과 entrypoint는 migrate·`create_all`·seed를 하지 않는다. T1의 `configure()` 추가가
  이 성질을 바꾸지 않아야 한다.
- 로그에 프롬프트 본문, 모델 응답, 회사 자료, 자격 증명, 쿼리 문자열, 담당자 이름을 넣지 않는다.
- 기존 산출물 계약(`bidops.*.v*`)과 파이프라인 스크립트 호출 방식을 바꾸지 않는다.
- `docker-compose.t7.yml`의 `document-worker`는 `network_mode: none`을 유지한다.
- 일상 운영에서 host 실데이터 bind mount를 쓰지 않는다. T3는 named volume으로 해결한다.

## 위임 방식

```bash
codex exec -m gpt-5.6-luna -c model_reasoning_effort=max \
  -C /home/jechoi/projects/bidops \
  -s workspace-write \
  -o <작업별 요약 파일> \
  "<작업 지시>"
```

작업 지시에는 항상 `docs/review/phase0-2/spec.md`의 해당 절과
`docs/standards.md`, `docs/engineering-notes.md`, 대상 모듈의 `AGENTS.md`를 읽으라는
요구를 포함한다.
