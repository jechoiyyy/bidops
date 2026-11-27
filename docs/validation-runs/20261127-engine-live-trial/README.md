# 2026-11-27 엔진 live 경로(OpenAI Responses API) 격리 시험

브랜치 `feat/engine-live-responses`(복제본 `/Users/temp/orca/bidops-final-1127`). [ADR-0081](../../tracking/decisions/0081-engine-live-responses-api.md)의 live 경로를 실제 모델 없이 확인한 기록이다. **외부 전송은 0건이다.** 품질·운영 활성화의 근거가 아니며 운영에는 아무것도 적용하지 않았다.

## 무엇을 돌렸나

| 항목 | 값 |
|---|---|
| 이미지 | `bidops:engine-live-a1a8ee0` — 커밋 `a1a8ee05`만으로 별도 worktree에서 `docker build --platform linux/amd64 -f docker/Dockerfile` (시험용, 배포 대상 아님) |
| 망 | `--internal` Docker 망 하나: PostgreSQL 17.11, 가짜 Responses 서버(`fake_responses.py`, 같은 이미지), 시험 컨테이너 |
| 시험 | `test_trial_live_e2e.py` — `run-trial.sh`로 실행 |
| 주입 | 없음. worker는 기본 `invoke_live`를 타고 0600 키 파일을 읽어 실제 `post_responses`(urllib, 프록시 무시·redirect 거부)로 `http://fake:8080/v1/responses`에 보낸다. 시험은 `HTTPS_PROXY`·`HTTP_PROXY`를 닿지 않는 주소로 두었다 |
| 흐름 | 합성 사전규격(원본 HWPX) + 합성 위키 → REST `requests` → `previews`(live manifest) → `approvals` → `engine_runs.run_once` → 조회 |

## 결과

`1 passed` (exit 0). `summary.json` 요약:

- run `completed`, `quality_status=unmeasured_reference`, 조회 상태 `result_ready`
- 예정 호출 3(합성 위키에 작업 단위 지도가 없어 units 단계 없음), 실제 전송 3회: extract → match → synth
- `engine_call` 3행 모두 `completed`, HTTP 200, USD 기록(가짜 usage 기준 합계 $0.003978 — 실제 비용 아님)
- 첫 요청 sha256 = 승인 manifest의 `first_request_sha256` = 가짜 서버가 받은 body의 sha256 (`9a9c75e5…`)
- 가짜 서버가 받은 요청은 모두 `Authorization: Bearer …`가 있었고 `store=false`였다
- 프록시 환경변수가 있어도 고정 주소로 직접 나갔다

## 같은 브랜치의 다른 검증

- 단위·통합(release image 런타임 + PostgreSQL 17): `tests/deep_review/test_engine_live.py` 14 통과 — wire parity(엔진 builder와 byte 동일), 프레임 변조·순서·문서 변경 거부, 예산 소진, 공고 호출 상한, HTTP 429·timeout·incomplete(한 번 기록, 재전송 없음), lease 상실, 원장 commit 실패 뒤 추가 전송 0, 키 없음, lease 만료 뒤 `reserved` → `outcome_unknown`, PostgreSQL의 승인 없는 live run 거부
- 엔진 패키지 1,577 통과, `scripts/engine-eval.py` 테스트 18 통과(이전 SDK판은 같은 테스트에서 11건 실패)
- 화면: `engine-review.spec.ts`에 live 자료 확인 창(수신자·예정 호출·상한·오늘 남은 상한) 추가, 영향 spec 112 통과

## 이 시험이 증명하지 않는 것

- **실제 OpenAI 응답.** 성공 응답 모양은 2026-11-27 실측 83건과 맞췄지만 실제 오류 body는 기록된 적이 없다.
- **전체 compose 스택.** web·analysis-worker 컨테이너, `engine-live` overlay의 secret 마운트, 첨부 worker·문서 worker를 거치는 실제 공고 흐름과 브라우저 조작은 이 시험에 없다. overlay 렌더는 `tests/app/test_compose_selection.py`로만 확인했다. 운영에 켜기 전 감독 시운전(운영 반영 P7)이 그 증거다.
- **결과 품질.** mock 답을 돌려주는 가짜 서버라 분석 내용은 의미가 없다.

## 다시 돌리기

```bash
./run-trial.sh bidops:engine-live-a1a8ee0 /Users/temp/orca/bidops-final-1127 <빈 시험 폴더> <로그 파일>
```
