# Deep Review v2 Luna 시안·품질 검증 계획

> 상태: **보류(결정적 부분 먼저 구현)** — 실행 전 계획, 외부 전송 미승인, 결과 미측정
>
> [ADR-0051](../tracking/decisions/0051-deep-review-v2-deterministic-subset.md)이 이 계획의
> 승인을 기다리지 않고 모델을 부르지 않는 부분(segment manifest·요구사항 inventory·검증
> 연결)만 먼저 채택했다. **이 계획 자체는 실행하지 않았고 어떤 지표도 측정하지 않았다.**
> 아래 내용은 그대로 계획으로 남으며, 실행하지 않은 계획을 근거로 쓰지 않는다.
>
> 기준일: 2026-09-03 (KST)
>
> 대상 모델: `gpt-5.6-luna`, reasoning effort `xhigh`
>
> 관련 문서: [첨부문서 분석 설계](document-analysis-design.md),
> [구현·검증 표준](../standards.md) (모델 전송 정책은 ADR-0050 완화 항목 참조)

## 1. 목적

이 실험은 제품 구현 전에 다음 두 질문에 답하기 위한 시안 검증이다.

1. 목적별 문서 분할과 역할별 분석으로 기획 담당자가 실제 사용할 수 있는 결과가 나오는가?
2. 현재 HWPX 구조화 결과가 그 품질을 지탱하는가, 아니면 다른 구조 추출 또는 PDF 보조가
   필요한가?

Luna는 운영 모델로 채택된 것이 아니다. 이 실험은 모델 품질과 목표 결과물의 형태를 보기
위한 reference 실행이며, 통과해도 운영 활성화·외부 모델 상시 사용·최종 입찰 결정 권한을
부여하지 않는다.

## 2. 현재 정책과 선행 조건

현재 모델 전송 정책(ADR-0050 완화 항목 참조)은 실험용 Luna·Sol에 공개 발주계획과 승인된
회사 역량 요약만 허용하고 제안요청서·첨부 전송을 금지한다. 공개 RFP라도 회사 판단과 결합하면
사내 자료로 취급하므로, 현 정책 상태에서는 이 실험을 실행할 수 없다.

실제 호출 전에 다음 내용을 가진 1회성 제한 예외를 별도 결정 기록으로 승인해야 한다.

- 목적: Deep Review v2 시안·품질 검증
- 허용 모델과 설정: `gpt-5.6-luna`, `xhigh`, Codex CLI
- 문서별 원본 URL, 공개 여부 확인, SHA-256
- 허용된 구조화 필드와 최소 회사 projection의 정확한 field allowlist
- 대표 1건 3회, 추가 5건 각 1회의 최대 실행 범위
- 실행자·승인자·승인 시각·실행 종료 조건
- 산출물 보관 위치, 접근자, 평가 종료 후 처리
- prompt·응답·회사자료의 Git·일반 로그·감사 detail 비보존
- provider 장애 시 자동 fallback 금지

이 예외는 지정된 hash와 실행에만 적용한다. 승인되지 않은 문서, 새 버전, 추가 모델,
추가 회사 필드로 확대하지 않는다.

### 2.1 기존 Codex deep-review adapter와의 구분

저장소에는 개발용 `codex-exec` reference adapter와 Compose overlay가 있으나, 이를 그대로
실험 경로로 사용하지 않는다.

- 운영 deep-review와 결합되어 있어 제품 실행과 reference 실험의 경계가 흐려질 수 있다.
- 현재 adapter의 payload allowlist는 identity·승인 metadata만 허용하며 RFP excerpt,
  profile, prior stage를 거부하므로 본 실험을 완주할 수 없다.
- 과거 설계에는 일반 vLLM prompt 재사용으로 금지된 RFP·profile이 전송될 위험이 기록되어
  있다.

따라서 본 실험은 제품 adapter를 느슨하게 바꾸지 않고, 승인된 입력만 둔 격리 디렉터리에서
수동 `codex exec`로 수행한다. 평가 뒤 선택된 설계를 별도 제품 구현으로 옮긴다.

## 3. 평가 입력

### 3.1 동결 corpus

| 구분 | 수량 | 실행 횟수 | 목적 |
|---|---:|---:|---|
| 대표 RFP | 1 | 독립 3회 | 결과 시안과 반복 일관성 확인 |
| 다양성 표본 | 5 | 각 1회 | 형식·목차·표·ID 체계 일반화 확인 |

총 6개 문서, 8개의 완주 결과를 만든다. 대표 문서는 사용자가 지정하며 나머지 5개는
고정 manifest로 재수집한다. 표본은 다음 특성을 가능한 한 겹치지 않게 포함한다.

- 원본 HWP와 원본 HWPX
- 목차 있음과 없음
- 요구사항 표 중심과 서술형 중심
- 단순 표와 병합 셀이 많은 표
- 명시적 요구사항 ID가 규칙적인 문서와 불규칙한 문서
- 공동수급·보안·인증 조항의 복잡도가 다른 문서

manifest는 source URL, 수집 시각, 파일명, detected MIME, byte size, source SHA-256,
document/structure version, extractor binding을 고정한다. 원본과 manifest가 다르면 해당
문서는 실행하지 않는다.

### 3.2 문서 입력

첫 기준선은 현재 검증된 HWPX 구조화 결과다. 모델에는 object key, 로컬 경로, 자격증명,
quarantine 위치를 보내지 않는다.

허용 문서 projection은 다음으로 제한한다.

- 문서·structure의 불변 식별자와 source hash
- 원문 순서가 있는 block ID, page, block type
- 문단 text와 표 셀 text
- table/row/column 등 근거 locator
- 결정적 규칙이 만든 heading·TOC·requirement ID 후보
- 입력 한계와 추출 warning

### 3.3 회사 최소 projection

회사의 현재 승인 profile 전체를 보내지 않는다. 실험용 최소 projection을 새 불변 JSON으로
만들고 실행 전에 사람이 실제 본문을 확인한다.

허용 후보는 다음과 같다.

- 업종·면허·직접생산·인증의 `confirmed|unknown|not_confirmed` 상태
- 공개 전송 승인을 받은 유사실적의 범주·규모 구간·역할
- 승인된 기술 capability와 근거 상태
- 인력의 익명화된 역할·숙련도·가용 상태
- projection version과 SHA-256

다음은 제외한다.

- 회사 프로필 원문과 실적 원문
- 고객명·담당자·개인정보
- 재무제표 원문, 계좌·세금·신용평가 문서
- 내부 단가·마진·수주 전략
- filesystem path, Git working-tree 경로, source line
- 승인되지 않은 자유서술 메모

projection에 없는 사실은 Luna가 추론하지 않고 `unknown`으로 처리해야 한다.

## 4. 사람 gold 작성

Luna 결과를 보기 전에 gold 초안을 만들고 사람이 확정한다. 모델 출력을 정답으로 사용하지
않는다.

gold는 다음을 포함한다.

- 확정된 장절·표 경계와 목적 taxonomy
- 명시적 요구사항 ID 전체 목록, 중복, ID 없는 핵심 의무
- 입찰 필수조건과 확인된 차단 여부
- 평가 항목·배점·금액·기간의 정답
- 회사 projection과의 매칭 상태
- 핵심 위험과 반드시 언급해야 할 전략 포인트
- 각 항목의 원문 locator와 exact quote
- 판정 불가 항목과 필요한 추가 자료

두 해석이 가능한 항목은 임의로 하나를 정답으로 만들지 않고 `ambiguous`와 허용 해석을
기록한다. Luna 결과는 gold 확정 뒤에만 unblind해 평가한다.

## 5. 실행 설계

### 5.1 격리

각 실행은 저장소 밖 임시 디렉터리 또는 Git에서 제외된 `.dryforge` 아래의 전용 0700
디렉터리에서 수행한다. 그 디렉터리에는 해당 호출에 승인된 입력, prompt, JSON Schema만
둔다.

- 저장소 루트에서 `codex exec`를 실행하지 않는다.
- user config와 project rules를 모델 실행에 로드하지 않는다.
- shell, hooks, apps, browser, computer use, multi-agent, plugin, image generation을 끈다.
- subprocess 환경은 Codex 인증과 TLS에 필요한 값만 allowlist하고 BidOps DB·MinIO·모델
  secret은 전달하지 않는다.
- 웹 검색을 켜지 않는다.
- 세션은 `--ephemeral`, sandbox는 `read-only`로 고정한다.
- output은 호출별 JSON Schema로 제한한다.
- JSONL 원문과 reasoning은 보존하지 않고 안전한 token·duration·status만 추출한다.

실행 명령의 기준 형태는 다음과 같다. 실제 binary version과 feature flag 지원 여부는
preflight 결과로 manifest에 기록한다.

```bash
codex exec \
  --model gpt-5.6-luna \
  --config 'model_reasoning_effort="xhigh"' \
  --config 'shell_environment_policy.inherit="none"' \
  --strict-config \
  --ephemeral \
  --sandbox read-only \
  --ignore-user-config \
  --ignore-rules \
  --skip-git-repo-check \
  --output-schema "$SCHEMA_PATH" \
  --output-last-message "$TEMP_OUTPUT_PATH" \
  -
```

실제 실행 wrapper는 지원되는 위험 도구 feature를 명시적으로 disable한다. prompt와 승인
input은 stdin으로 전달한다. background 실행을 사용하지 않고 각 PID와 종료 상태를 확인한다.

### 5.2 호출 단위

하나의 완주 결과는 다음 계약 호출로 구성한다.

1. 결정적 segmenter가 후보 manifest와 requirement inventory를 만든다.
2. 모호한 후보가 있을 때만 Luna taxonomy 분류를 호출한다.
3. 입찰·사업성 역할을 호출한다.
4. 기술 적합성 역할을 호출한다.
5. 위험·거버넌스 역할을 호출한다.
6. 각 결과를 schema와 결정적 근거 검증기로 검사한다.
7. 검증된 claim만 Luna 종합 역할에 전달한다.
8. 최종 planner report와 validation scorecard를 만든다.

세 역할 호출은 동일한 frozen segment manifest를 사용하며 서로의 결론을 입력으로 받지
않는다. 종합 역할만 검증된 세 결과를 소비한다. 이 구조로 역할 간 독립성과 충돌을 측정한다.

### 5.3 반복 실행

대표 RFP의 세 실행은 다음을 모두 고정하고 새 execution ID만 사용한다.

- 문서와 회사 projection bytes
- segmenter·taxonomy version
- model과 reasoning effort
- role prompt와 JSON Schema digest
- generation 관련 설정
- 역할 호출 순서와 입력 slice

세 결과를 병합하거나 하나를 정답으로 선택하지 않는다. 각 결과를 독립 채점하고 핵심 claim,
권고, unknown, locator의 변동을 비교한다.

추가 5개 문서는 각각 한 번 실행한다. 대표 문서에서 prompt를 본 뒤 추가 표본별로 prompt를
바꾸지 않는다. 변경이 필요하면 prompt version을 올리고 앞선 결과와 다른 실험으로 기록한다.

## 6. 역할별 출력 계약

모든 출력은 strict JSON이며 자유 형식 Markdown만으로 성공 처리하지 않는다.

### 6.1 입찰·사업성 결과

- 자격 조건 ID, 공고 evidence, 회사 fact key
- `met|not_met|unknown`
- 필수 여부와 확인된 차단 여부
- 평가 항목, 최대 배점, 계산 상태, 계산 근거
- 공동수급 필요성, 역할 후보, 확인 사항
- 예산·기간·계약 위험
- 권고 후보와 조건

### 6.2 기술 적합성 결과

- 모든 inventory requirement ID
- `ready|needs_confirmation|gap|not_applicable`
- 문서 evidence와 회사 fact key
- gap 설명, 보완 방법, 외부 협력 필요성
- 필요한 역할과 선행 의존성
- M/M `computed|conditional_range|unknown` 및 전제

### 6.3 위험·거버넌스 결과

- 위험 ID와 영역
- `blocking|major|medium|low`
- 의무·영향·완화 행동·담당 역할·기한·잔여 위험
- 사실과 전략 추론의 분리
- 품질·인증·보안·비용 정산·공동수급 coverage

### 6.4 종합 planner report

- `추진 검토|조건부 추진 검토|보류|검토 종료` 시스템 권고
- 권고의 검증된 premise claim ID
- 입찰 전 해소할 차단 조건
- 기술 gap과 파트너 전략
- 제안서·PT 차별화 포인트
- 담당자별 다음 행동과 기한
- unknown과 문서 한계
- 사람 최종 결정이 필요하다는 명시

## 7. 산출물 패키지

각 execution은 다음 구조의 검토 패키지를 만든다. 경로는 예시이며 실제 root는 1회성 승인
기록에서 확정한다.

```text
<eval-root>/<execution-id>/
├── input-manifest.json
├── segment-manifest.json
├── eligibility-business.json
├── technical-fit.json
├── risk-governance.json
├── planner-report.json
├── planner-report.md
├── evidence-trace.json
├── validation.json
└── scorecard.json
```

모델의 최종 JSON은 schema 검증과 canonicalization을 통과한 뒤 역할 artifact로 저장한다.
검증 전 임시 output, JSONL stdout, stderr 본문은 보존하지 않는다. 일반 로그에는 execution
ID, digest, safe error code, token, duration만 남긴다.

검토가 끝나면 공개 가능한 digest와 비민감 scorecard만 `docs/validation-runs`에 기록한다.
회사 projection, prompt 본문, role 결과 전문은 Git에 넣지 않는다.

## 8. 품질 지표와 통과 기준

### 8.1 차단 지표

| 지표 | 기준 | 실패 처리 |
|---|---:|---|
| 대표 문서 명시적 requirement ID recall | 100% | 설계 미채택 |
| 확정 segment 경계 오류 | 0건 | segmenter 재설계 |
| 필수 자격 false positive | 0건 | 입찰 권고 경로 미채택 |
| source hash·locator·quote 검증 | 100% | 해당 claim 배제, 전체 완주 실패 |
| 배점·금액·기간 산술 일치 | 100% | 결정적 계산 재설계 |
| 회사 결측값의 `unknown` 보존 | 100% | prompt/contract 미채택 |

### 8.2 품질 지표

| 지표 | 목표 |
|---|---:|
| 핵심 claim 사람 동의율 | 80% 이상 |
| 자동 확정 가능한 segment 비율 | 70% 이상 |
| 필수 분석 영역 coverage | 100% |
| 대표 3회 requirement 상태 일치율 | 90% 이상 |
| 대표 3회 시스템 권고 일치 | 3회 동일 또는 차이가 모두 gold의 `ambiguous` 범위 |
| 근거 없는 전략·수치 claim | 0건 |

분모가 없거나 gold가 완료되지 않은 지표는 `미측정`이며 통과가 아니다. 평균 점수가 좋아도
차단 지표 하나가 실패하면 제품 구현 승인 근거로 사용하지 않는다.

### 8.3 사람 평가

기획 담당자는 모델명을 가린 상태에서 다음을 평가한다.

- 문서를 다시 찾지 않고도 핵심 조건을 이해할 수 있는가?
- 누락보다 장황함이 심하지 않은가?
- 시스템 권고의 조건과 unknown이 분명한가?
- 기술 gap과 파트너 필요성이 실행 가능한 행동으로 표현되는가?
- 사실, 계산, 전략 의견을 구분할 수 있는가?
- 제안서 작성과 내부 의사결정에 실제 도움이 되는가?

자유 의견은 claim 또는 report section ID에 연결한다.

## 9. 결과에 따른 결정 규칙

### 9.1 HWPX 기준선 채택

모든 차단 지표와 품질 목표를 충족하면 HWPX를 의미 구조 canonical로 유지하고
[첨부문서 분석 설계](document-analysis-design.md)에 따라 제품 구현을 진행한다.

### 9.2 구조 추출 A/B

다음 실패가 HWPX 추출에 집중되면 해당 문서만 `edwardkim/rhwp` direct structure와 PDF
파생본으로 다시 만든 뒤 동일 gold·prompt·모델로 A/B한다.

- 표 셀·요구사항 ID 누락
- heading/TOC 경계 오류
- page locator 불일치
- 읽기 순서 오류

direct structure가 전수성과 locator를 개선하면 pinned CLI subprocess 통합을 설계한다.
PDF만 개선되면 HWPX canonical은 유지하고 PDF를 시각·페이지 검증 파생본으로 추가한다.
둘 다 통과하지 못하면 해당 문서 유형은 사람 준비 단계로 보낸다.

### 9.3 모델 결과 미채택

분할·inventory는 통과하지만 Luna 역할 결과가 기준에 미달하면 결정적 분할 설계만 채택한다.
운영 분석은 현행 승인된 사설 Qwen 경계를 유지하고 같은 role contract를 별도 평가한다.
이번 범위에는 Qwen matched baseline이나 Sol 상한선 실행을 추가하지 않는다.

### 9.4 평가 후 문서·구현 전환

사람 scorecard 승인 뒤에만 다음 작업을 시작한다.

1. 선택 결과와 기각 대안을 ADR로 기록한다.
2. `ARCHITECTURE.md`, `business-rules.md`, `contracts.md`,
   `deep-review-erd.md`에서 현재와 목표를 갱신한다.
3. segment와 role artifact의 schema version을 확정한다.
4. 기존 worker·validator·report/API/UI의 구현 계획을 선택 결과에 맞게 확정한다.
5. 구현과 회귀 검증을 수행하되 Luna를 운영 자동 fallback으로 추가하지 않는다.

## 10. 실행 체크리스트

### 호출 전

- [ ] 1회성 예외 결정이 승인됨
- [ ] 6개 문서의 공개 여부와 SHA-256이 고정됨
- [ ] 회사 최소 projection 본문을 사람이 승인함
- [ ] gold가 Luna 결과를 보기 전에 확정됨
- [ ] Codex CLI·모델·reasoning effort preflight가 통과함
- [ ] 격리 directory와 환경 allowlist가 검증됨
- [ ] 실제 전송 payload preview가 승인됨

### 호출 후

- [ ] 예정된 8개 execution 외 추가 호출이 없음
- [ ] 모든 output이 schema와 source 검증을 통과하거나 실패로 기록됨
- [ ] raw JSONL·stderr·임시 output이 남지 않음
- [ ] token·duration·digest가 safe telemetry로 기록됨
- [ ] 사람 blind review와 gold 비교가 완료됨
- [ ] 미측정 값을 0이나 통과로 기록하지 않음
- [ ] 결과가 운영 활성화나 최종 Go/No-Go로 자동 반영되지 않음

이 문서는 실험 실행 명세다. 체크리스트와 1회성 승인 없이 `codex exec`, API 또는 기존
Compose overlay를 이용해 실제 RFP를 외부 모델에 전송하지 않는다.
