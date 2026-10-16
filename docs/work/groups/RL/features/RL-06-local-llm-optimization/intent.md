# 토큰 계측과 로컬 LLM 최적화 검토 — intent

- 기능 ID: `RL-06-local-llm-optimization`
- 상위 항목: roadmap §RL 표 7행, 사용자 Q3("구현 뒤 로컬 LLM 토큰 최적화 단계"), ADR-0073 결정 5 마지막 문장
- 크기: M — codex-runner 응답에 토큰 수 추가(응답 키 추가형, contract 불변), 단계별 토큰·지연 계측 열 6개(migration 1), 사용량 보고 CLI 1개, 실험 보고서 1개. **모델 교체·로컬 LLM 호출은 없다**(제약: RL 호출은 Luna 하나). 착수는 RL-03·04 `validating` 이후.
- 작성일: 2026-10-16

## 문제

RL-03·04가 공고마다 10~20회 Luna를 호출한다. 어느 단계가 토큰을 쓰는지 숫자가 없으면 "로컬 LLM으로 바꿀 가치가 있는 단계"를 고를 수 없고, 바꾼 뒤 품질이 떨어졌는지 비교할 기준도 없다. 지금 `prompt_tokens`·`output_tokens`·`latency_ms`는 회사 핏 attempt에만 있고 카드 분석 단계·제안서 절에는 없다.

## 기대 결과

- codex-runner가 토큰 수를 돌려주고(지금은 지연만 준다), 카드 분석 단계(`card_analysis_stage`)와 제안서 절(`proposal_section`)에 호출별 토큰·지연이 저장되고, `usage-report` CLI가 기간별·단계별·공고별 호출 수·토큰·지연·실패율을 JSON과 Markdown으로 낸다.
- 실험 보고서가 (1) 단계별 토큰 분포, (2) 로컬 LLM 후보 단계(예: 1층 추출 batch, 제안서 `requirements` 절)와 제외 단계(종합·역할), (3) 채택 기준(RL-05 gold 10건에서 판정 일치·차단 recall·카드 일치 비열화 + 호출 비용), (4) 다음 기능 제안을 가설→기준→명령→결과→판단 순으로 남긴다. 실제 로컬 모델 호출·정책 변경은 후속 기능.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 계측 저장 | RL-03·04 실행 뒤 | 단계·절 행마다 `prompt_tokens`·`output_tokens`·`latency_ms` 비null(runner가 준 값; 없으면 null 보존) |
| 사용량 보고 | `python -m app.deep_review.cli usage-report --from 2026-10-20 --to 2026-10-31 --out <dir>` | `usage.json`·`usage.md`: 단계별 합계·중앙값·p90, 공고별 호출 수, 실패율, 일별 cap 소진 |
| 보고서 | `docs/experiments/<날짜>-local-llm-token-optimization.md` | 네 절 + 후보 단계 표 + 채택 기준 + 결론(실험 없음·제안만) |

## 선행·후속 기능

- 선행: `RL-04-proposal-draft`(절 계측 대상), `RL-03`(단계 계측 대상), `RL-05`(품질 비교 기준).
- 후속: 로컬 LLM 실제 비교 실험(별도 기능, 정책·allowlist·승인 변경 필요).

## 영향 범위

- 모듈·컴포넌트: codex-runner(`runner.py` usage 파싱·응답 키 2개), deep_review(`luna_client.py` InvocationResult, `models.py` 열 추가, `card_analysis.py`·`proposal_draft.py`가 usage 저장, `cli/usage_report.py`), docs/experiments(신설).
- 큰 틀 문서의 절: contracts.md(열·CLI), deep-review-erd.md(열), operations.md(보고 명령).
- 데이터·저장소: `card_analysis_stage`에 nullable 열 6개(migration; `proposal_section` 토큰 열은 RL-04가 둠), 권한 변경 없음.
- 외부 서비스·호출: 없음.

## 제약

- (공통) feature.json constraints. 특히 "RL 호출은 Luna 하나, LiteLLM·Qwen·Terra 사용 금지".
- (기능별) 보고서는 실무 화면에 넣지 않는다(운영 정보). 토큰 수는 payload 내용이 아니므로 로그 가능하나 prompt 원문은 기록하지 않는다.

## 범위 밖

로컬 모델 호출·비교 실험 실행, 정책·runner **contract(schema allowlist)** 변경(응답 키 추가는 범위 안), 비용 단가 산정, 화면.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 계측 열 위치 | RL-03·04 spec은 `proposal_section`에만 토큰 열 | 카드 단계 테이블에 없음 | RL-06이 `card_analysis_stage`에 열 추가(RL-03 구현이 끝난 뒤 migration) |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| 없음 | | 사용자 Q3 "구현 뒤 로컬 LLM 토큰 최적화"를 "계측 + 검토 보고서"로 해석(실제 전환은 후속) |
