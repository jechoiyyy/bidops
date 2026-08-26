# Mock 전체 워크플로우 E2E 결과

- 실행일: 2026-08-26
- 격리 Compose project: `bidops-step-r26bk01680717`
- 대상 공고: 내부 notice `1` / 공고번호 `R26BK01680717`
- 분석 provider: `mock-analysis`
- runtime model: `bidops-deterministic-mock-v1`
- policy quality: `reference_workflow_unmeasured`, `deployable=false`
- OpenAI/Codex: 비활성

이 결과는 워크플로우 상태 전이와 저장·검증 경계의 인수 결과다. Mock의 claim 내용과 고정
권고는 Qwen 품질 또는 실제 사업 판단을 승인하지 않는다.

## 최초 성공 계보

- ready bundle: `de013c3c-a9a6-4f93-bc06-2c75684e2e9b` (revision 9, 문서 2개)
- deep review: `773b7750-dfda-4390-b583-918edf298489`
- machine revision: `c9094337-cdf0-40f0-9f35-556b37cbb55a`
- machine validation: `7e91e8e3-3241-4acb-a3e1-d60e70f78194` / `passed`
- 원문 이동 확인 evidence: 91건

| Stage | 상태 | claim | evidence | invocation slice |
|---|---:|---:|---:|---:|
| requirements_and_evaluation | completed | 31 | 31 | 14 |
| delivery_risk_economics | completed | 60 | 60 | 23 |
| synthesis_and_validation | completed | 9 | 0 | 9 |

사람 mutation도 실제 API로 수행했다.

- human full revision: `f9c4f21b-909e-46ff-903a-f7ed8ded338b`
- human validation: `0f1e9d01-6c35-4e6f-9408-9f8894eeb167` / `passed`
- revision history: machine → human, 총 2개
- final opinion: `6f5b8210-b61f-4ba1-9d32-d51690b5fbed` / `조건부 추진`

최종 의견은 “Mock 결과임을 전제로 상태 전이만 승인”하는 테스트 fixture다.

## 새 첨부 이후 계보

원본 공고 PDF와 같은 bytes를 다른 수동 첨부 이름으로 등록했다. 두 document version은 서로
다르지만 SHA-256과 content object는 같았고, 새 ready bundle과 deep review가 생성됐다.

- 새 ready bundle: `020c2020-e773-470e-a21a-97f42cb97352` (revision 10, 문서 3개)
- 새 deep review: `be147c78-f9e1-4c64-bf43-1bd317960216`
- 새 review 상태/validation: `completed` / `passed`
- 이전 review 재조회: human revision 1개와 final opinion 1개가 그대로 보존됨
- 새 review ID는 이전 review와 다르며 사람 revision/final opinion을 승계하지 않음

## 테스트 중 발견해 보정한 공통 흐름 결함

Stage 2 입력 조립기가 2KB를 조금 넘는 정상 회사 profile fact를 거부했다. profile slice 예산을
4KB로 늘리고 Stage 2 문서 slice 예산을 15KB로 줄였다. 대표 입력에서 Stage 2 최대 prompt는
19,006 Unicode 문자로 24,000자 상한 안에 남았다.

## 자동 회귀

- backend: `296 passed, 4 skipped`
- skip 4개: 별도 isolated T7 MinIO opt-in이 필요한 테스트
- Mock·분석·보고서·B→C 집중 회귀: `96 passed`

다음 단계는 Mock override를 제거하고 승인된 vLLM/Qwen provider로 새 review를 생성한 뒤,
55개 fixture의 재현율·사람 일치율·근거 부족 오판율과 timeout/잘린 JSON 재시도를 측정하는 것이다.
