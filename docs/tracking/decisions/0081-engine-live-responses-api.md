# 제품의 엔진 live 분석은 OpenAI Responses API로 직접 호출한다

- 상태: 채택 — 2026-11-27 사용자 결정("Responses 방식으로 반드시", "회사핏·심층검토 엔진을 테스트한 방식으로 전환해 최종 완성본으로", 엔진 경로만 전환하고 codex-runner 경로는 유지). 코드는 RL-11 4단계. 운영 활성화·실제 전송·품질 인수는 각각 직전 승인 대상이다.
- 일자: 2026-11-27
- 근거: [토큰·비용 실측](../../validation-runs/20261126-luna-token-cost/README.md)(codex-exec 캐시 적중 0, 명시 캐시 경계로 match·synth 문서 캐시 읽기), 2026-11-27 매치 19건 실행(19/19 ok, 83회 호출, $1.25, 캐시 적중 33%, 건당 평균 238초, `.sdlc/local-runtime/prespec1123-25-engine-20261127/`), [RL-11 개정안](../../work/groups/RL/features/RL-11-live-prespec-engine/track-start-entry.md)
- 관련: ADR-0078(사람이 여는 분석 요청·건별 승인)·ADR-0069(사용자 요청 Luna, codex-exec 유지)·ADR-0074(엔진 기준선)·ADR-0050(모델 전송 정책)·ADR-0080(회사 핏)

## 결정

1. **엔진 live 분석의 전송 경로는 OpenAI Responses API 하나다.** 모델 `gpt-6-luna`, `reasoning.effort=high`, `store=false`, 재시도 없음, 주소는 코드에 고정한 `https://api.openai.com/v1/responses`(운영은 다른 주소를 거부). 요청 body는 2026-11-27에 측정한 그대로다: system을 developer 메시지로, 문서를 user 부분으로 두고 extract·match·synth의 문서 뒤에 명시 캐시 경계(`prompt_cache_breakpoint`, 30분)를 둔다.
2. **엔진 프로세스는 키도 네트워크도 갖지 않는다.** `bid_deep_engine.runner --live-ipc`는 호출마다 frame 한 줄을 내고 응답 frame을 기다린다. HTTP와 키는 analysis-worker의 supervisor(`engine_live.py`)만 가지며, 키는 compose secret으로 analysis-worker에만 마운트한다. web 프로세스는 엔진 패키지를 import하지 않으므로 supervisor는 같은 wire 상수를 따로 두고, 두 builder가 같은 bytes를 만드는지 테스트로 묶는다.
3. **보내기 전에 검사하고 기록한다.** frame마다 body를 재구성해 상수·단계 순서(extract → units ≤2 → match → synth)·공유 문서를 확인하고, 첫 요청은 승인된 미리보기의 hash와 같아야 한다. 이어서 advisory lock 아래 KST 하루·공고별 상한을 확인하고 `engine_call` 행을 `reserved`로 commit한 뒤에만 보낸다. 결과를 기록하는 commit이 실패하면 더 보내지 않는다. 결과를 모르는 요청은 상한 한 칸을 쓰고 다시 보내지 않는다.
4. **승인은 ADR-0078 그대로 공고별이다.** live 미리보기 manifest에 수신자·wire 버전·첫 요청 hash·예정 호출 수·호출 timeout·상한·단가표를 넣어 digest로 고정한다. DB는 승인된 live 미리보기가 없는 live run을 commit 시점에 거부한다. 결과는 `unmeasured_reference`다.
5. **시운전 상한은 하루 1건·8회·$1, 공고당 8회다.** 값이 없거나 0이면 live 모드는 기동을 거부한다. 상향은 별도 승인이다.
6. **codex-exec 경로는 그대로 둔다.** RL 카드 판정·제안서 초안·사용자 요청 Luna 심층검토(codex-runner, ADR-0069)와 `luna_identity`의 codex-exec 고정은 바꾸지 않는다. 제품 밖 평가 도구 `scripts/engine-eval.py`도 기본은 Responses API이고 codex는 `--transport codex`로 명시할 때만 쓴다.

## 그대로 둔 것

분석 요청은 사람의 추적 시작·`분석 요청`에서만 생긴다. 회사 입력은 루트랩 위키 묶음 하나(입력 v3)다. 엔진 결과는 추적 상태나 최종 Go/No-Go를 바꾸지 않는다. RL-05 reject와 RL-04 partial은 그대로다.

## 결과와 한계

- chunking은 하지 않는다. 한 요청의 추정 입력이 32만 토큰을 넘으면 보내기 전에 멈춘다(관측 최대 30.7만).
- 엔진 실행은 analysis-worker 공용 슬롯 하나에서 한 건씩 돈다(건당 약 4분). C-2는 claim 순서로만 앞서고 실행 중에는 양보하지 않는다.
- live 오류 응답 body는 기록된 적이 없어 가짜 서버의 오류 경우는 문서 형식만 따른다. 첫 감독 시운전에서 실제 오류 형식을 확인하기 전에는 "검증됨"으로 적지 않는다.
- 결과 품질은 미측정이다. 사람 채점·인수(RL-11 5단계) 전에는 운영 기본 표시나 품질 근거로 쓰지 않는다.
