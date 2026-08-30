# 심층 검토 DB 읽기 안내서 — `deep-review-erd.md` 해설

> 대상 독자: 이 저장소에 처음 들어온 개발자
> 성격: 해설 문서. 계약은 `docs/deep-review-erd.md`이고 이 문서는 그 계약을 **왜 그렇게 썼는지** 설명한다.
> 충돌 시 항상 `deep-review-erd.md`와 `web/backend/app/models.py`가 우선한다.

---

## 0. 이 문서를 읽는 법

`deep-review-erd.md`는 승인·동결된 설계 계약이다. 계약서는 "무엇을 지켜야 하는가"만
적혀 있어서 처음 보면 제약 조건 목록처럼 읽힌다. 이 문서는 그 앞단의 질문에 답한다.

- 이 DB는 **어떤 문제**를 풀려고 만들어졌는가
- 38개 테이블이 **왜 그렇게 나뉘어** 있는가
- 실제 데이터가 **어떤 순서로 흘러가는가**
- 여기 쓰인 설계 기법이 일반적으로 **어떤 이름**으로 불리는가

읽는 순서 추천: 1장(문제) → 2장(큰 그림) → 6장(시나리오) → 3~5장(계층 상세) → 7장(설계 기법).
시간이 없으면 1, 2, 6장만 읽어도 대화는 가능하다.

---

## 1. 이 DB는 무엇을 위한 것인가

### 1.1 업무 맥락

BidOps는 나라장터(공공조달 사이트) 입찰을 다룬다. 업무 흐름은 크게 두 단계다.

```
[1차 선별]  하루 수백 건의 공고를 훑어서 "볼 만한 것"만 남긴다  → 기존 13개 테이블
[심층 검토]  남은 소수를 첨부문서까지 읽고 참여 여부를 판단한다  → 신규 25개 테이블
```

`deep-review-erd.md`가 설계하는 것은 **두 번째 단계**다. 공고 하나에 붙은 제안요청서
PDF·HWP 수십 장을 LLM(Qwen)에게 읽히고, "우리가 이 사업에 들어갈 만한가"를 정리한
보고서를 만든 뒤, 사람이 최종 판단을 내리는 과정 전체를 DB에 기록한다.

### 1.2 핵심 제약 — 왜 그냥 `reports` 테이블 하나로 안 되는가

순진하게 만들면 이렇게 된다.

```sql
-- 이렇게 하면 안 되는 설계
CREATE TABLE deep_report (
  notice_id  bigint,
  summary    text,      -- LLM이 쓴 글
  decision   text,      -- 사람이 고른 값
  updated_at timestamptz
);
```

이 설계는 다음 질문에 하나도 답하지 못한다.

| 질문 | 순진한 설계의 답 |
|---|---|
| "이 보고서의 '사업 예산 12억'은 어느 파일 몇 페이지에서 나왔나?" | 모름 |
| "3주 전 담당자가 승인할 때 봤던 보고서 내용이 뭐였나?" | 덮어써서 사라짐 |
| "그때 첨부문서가 그 뒤에 교체됐는데, 판단은 옛날 문서 기준이었나?" | 모름 |
| "같은 입력으로 다시 돌리면 같은 결과가 나오나?" | 검증 불가 |
| "이 결론은 원문 근거인가, 모델이 지어낸 것인가?" | 구분 불가 |

이 다섯 질문이 이 DB 설계의 전부다. 공공조달은 금액이 크고 판단 근거를 나중에 소명해야
하므로, **"언제, 무엇을 근거로, 누가 판단했는지"가 사후에 그대로 재구성되어야** 한다.
CLAUDE.md의 강제 게이트 — "추정하지 않는다", "근거는 원문 위치와 연결한다",
"자동 보정하지 않는다" — 가 DB 스키마 수준으로 내려온 결과가 이 38개 테이블이다.

### 1.3 설계를 지배하는 3원칙

**원칙 1 — 불변(immutable)과 추가(append-only)**
분석 결과, 보고서, 검증, 최종 의견은 `UPDATE`하지 않는다. 수정은 **새 행**으로 표현한다.
"수정 이력"이 부가 기능이 아니라 저장 방식 그 자체다.

**원칙 2 — 고정(pinning)과 스냅샷(snapshot)**
분석을 시작하는 순간 입력(문서 묶음·회사 프로필·분석 정책)을 그 시점 상태로 **박제**한다.
분석 중이나 그 후에 원본이 바뀌어도 이미 만들어진 보고서의 근거는 흔들리지 않는다.

**원칙 3 — 근거 없는 주장 금지(evidence-first)**
LLM이 만든 모든 문장은 `claim` 한 행이 되고, 각 claim은 `evidence_ref`로 원문 위치를
가리켜야 한다. 근거를 못 대면 그 claim은 `unsupported` 상태로 남고 사람에게 넘어간다.
빈칸은 지어내지 않고 `unknown`으로 남는다.

---

## 2. 큰 그림 — 5개 계층

38개 테이블은 다섯 덩어리다. 데이터는 위에서 아래로 흐른다.

```
┌─────────────────────────────────────────────────────────────┐
│ ① 레거시 수집·선별 (13)   run, notice, judgment, review …     │
│    "어떤 공고가 있고, 1차 선별에서 어떻게 판정했나"             │
└───────────────────────────┬─────────────────────────────────┘
                            │ notice_id
┌───────────────────────────▼─────────────────────────────────┐
│ ② 문서 (8)   content_object → document_version → structure   │
│              → block, 그리고 document_bundle                 │
│    "첨부파일의 바이트, 업무적 의미, 구조화 결과, 확정 묶음"      │
└───────────────────────────┬─────────────────────────────────┘
                            │ bundle_id
┌─────────────────┐         │         ┌─────────────────────────┐
│ ③ 지식 (3)      │         │         │ ⑤ 운영 (3)              │
│ profile_version │─────────┤         │ work_job                │
│ policy_version  │         │         │ idempotency_record      │
│ "우리 회사 역량,│         │         │ audit_event             │
│  분석 규칙"     │         │         │ "큐, 중복방지, 감사"     │
└─────────────────┘         │         └───────────┬─────────────┘
                            │                     │
┌───────────────────────────▼─────────────────────▼───────────┐
│ ④ 분석 (11)  deep_review → attempt → stage → claim           │
│              → evidence_ref → report_revision                │
│              → validation_run → final_opinion                │
│    "실행, 주장, 근거, 보고서, 검증, 사람의 최종 판단"           │
└─────────────────────────────────────────────────────────────┘
```

한 문장 요약: **① 어떤 공고를, ② 어떤 문서 묶음으로, ③ 어떤 회사역량·규칙에 비추어,
④ 분석하고 근거를 달아 보고서를 만들고 사람이 결정했으며, ⑤ 그 실행을 안전하게 굴렸다.**

### 2.1 물리적 배치 — DB에 안 들어가는 것

중요한 경계 하나. **파일 원본은 PostgreSQL에 없다.**

```
PostgreSQL (bidops schema)          MinIO / S3 (버전 관리 켜짐)
─────────────────────────           ────────────────────────────
sha256, 크기, MIME                  ← 실제 PDF/HWP 바이트
객체 위치(key, version_id)          ← 구조화 결과 전체 JSON
근거 조회용 블록 투영(projection)    ← 모델 원응답(암호화, 90일)
```

이유는 두 가지다. 하나는 용량(월 32,000 페이지 규모의 원문·구조 JSON을 DB에 넣으면
백업·복구가 감당 안 된다), 다른 하나는 보존 정책 분리(모델 원응답은 90일 후 소멸시켜야
하는데 객체 스토리지의 lifecycle 정책이 이 일에 맞다).

DB에는 `sha256`과 객체 위치만 남는다. 그래서 "DB의 이 행이 가리키는 파일이 진짜 그 파일이
맞나"는 언제든 해시로 검증할 수 있다.

---

## 3. 계층 ① — 레거시 13개 테이블

기존 SQLite로 돌던 수집·1차선별 시스템이 그대로 옮겨온 부분이다. 새로 설계한 게 아니라
**손실 없이 이관**하는 것이 목표였다.

```
run  ──< notice ──< judgment ──< perspective / screening_evidence / counterargument
                 │            └< verification_item, matched_performance
                 ├──< attachment      (첨부파일 목록 — ②의 입구)
                 ├──< review ──< verification_answer   (사람의 1차 검토)
                 └──< ingest_warning  (수집 경고)
     agency_portal (발주기관 포털 정보)
```

이관 규칙에서 배울 점 두 가지.

**컬럼을 함부로 버리지 않는다.** 이관 도구는 manifest에 없는 legacy 컬럼을 발견하면
"모르는 컬럼이니 버리자"가 아니라 **중단**한다. 데이터 이관에서 조용한 손실이 가장 나쁘다.

**이름 변경은 충돌 때문에만 한다.** 기존 `evidence` → `screening_evidence`로 바꾼 이유는
신규 분석 근거(`evidence_ref`)와 개념이 완전히 달라서다. 하나는 1차 선별의 판단 사유,
하나는 원문 위치를 가리키는 인용이다. 이름이 같으면 반드시 누군가 잘못 조인한다.

### 3.1 "사람"을 테이블로 만들지 않은 이유

이 시스템에는 **로그인이 없다.** 사내망 접근 제한이 유일한 경계고, 담당자는 화면에서
자기 이름을 문자열로 입력한다.

그래서 `actor` 테이블을 만들지 않았다. 대신 사람이 뭔가를 바꾸는 모든 행에
`claimed_name`(자칭 이름)을 그대로 박아 넣는다.

```
review.reviewer_snapshot      "김철수"
final_opinion.claimed_name    "김철수"
audit_event.claimed_name      "김철수"
```

여기서 규율이 하나 붙는다. **같은 이름을 같은 사람으로 합치지 않는다.** 인증이 없으므로
"김철수"라고 적은 두 행이 동일인이라는 보장이 없다. 이름을 UUID identity로 정규화하면
검증되지 않은 사실을 DB가 사실인 것처럼 만들어버린다. 나중에 SSO가 들어오면 검증된
issuer/subject로 **새** actor를 만들고, 과거 행은 계속 "미인증 이름 기록"으로 남긴다.

`actor_kind`가 `'system'`이면 `claimed_name`은 null이다. 그리고 HTTP API로는 `system`을
선택할 수 없다. 워커가 한 일을 사람이 한 것처럼 위장하거나 그 반대가 되면 감사가 무너진다.

---

## 4. 계층 ② — 문서 8개 테이블 (이 설계의 심장)

가장 이해하기 어렵고, 가장 배울 게 많은 부분이다. "PDF 파일 하나"가 왜 4개 테이블로
쪼개지는지가 요점이다.

### 4.1 4단 분리

```
content_object      "이 바이트 뭉치"           ← sha256이 정체성
    │
    ├─ content_object_location   "MinIO 어디에 있나"  (같은 바이트, 여러 위치)
    ├─ content_scan              "바이러스 검사 결과"
    │
    ▼
document_version    "이 바이트가 업무적으로 무엇인가"
                    (어느 공고의, 제안요청서인가 과업지시서인가, 몇 차 개정인가)
    │
    ▼
document_structure  "이 문서를 구조화한 결과"
                    (어떤 추출기 버전으로 뽑았나, 몇 페이지 몇 블록인가)
    │
    ▼
document_block      "9페이지 3번째 표의 이 셀"     ← 근거 locator 조회용
```

**왜 `content_object`와 `document_version`을 나누는가?**

같은 PDF 파일이 여러 공고에 첨부되는 일은 흔하다(표준 계약서, 공통 과업지시서). 바이트는
하나인데 업무적 의미는 여러 개다.

```
content_object(sha256=abc123…)          ← 파일 하나, 저장도 한 번
     ├── document_version(notice=101, role='제안요청서', version=1)
     ├── document_version(notice=205, role='첨부', version=1)
     └── document_version(notice=205, role='첨부', version=2)   ← 개정판 등록
```

이걸 합쳐두면 "파일을 지우면 다른 공고가 깨지는" 문제가 생기고, 중복 저장·중복 스캔·중복
구조화 비용도 그대로 든다. 이 기법의 일반적 이름은 **content-addressed storage**다.
Git이 blob을 해시로 다루는 것과 정확히 같은 아이디어다.

**왜 `document_structure`를 따로 두는가?**

구조화(PDF → 페이지·블록·표 JSON)는 추출기 버전에 따라 결과가 달라진다. 그래서 structure는
`extractor_name`, `extractor_version`, `upstream_commit`을 기록한다. 6개월 뒤 "왜 그때는
이 표를 못 읽었지?"에 답할 수 있어야 한다.

정본은 객체 스토리지의 `bidops.document-structure.v1` JSON이고, `document_block`은 그중
**근거 조회에 필요한 만큼만 뽑아둔 투영(projection)**이다. 보고서에서 "9페이지 표 3-2"를
클릭했을 때 빠르게 원문을 찾기 위한 인덱스지, 구조 데이터의 원본이 아니다. 페이지 메타데이터와
표 셀 좌표는 payload와 block `attributes`에 둔다.

### 4.2 안전 경로 — quarantine 우선

업로드된 파일은 **무조건 격리(quarantine) 네임스페이스에만** 먼저 쓴다.

```
업로드 → quarantine에 기록 → 다시 읽어 sha256/크기 재검증
       → MIME/magic/archive/PDF 구조/ClamAV 검사
       → 전부 통과한 바이트만 source 네임스페이스에 새로 기록
       → 그제서야 업무 참조(document_version) 커밋
```

핵심은 두 가지다.

- **먼저 쓰고 다시 읽어서 검증한 뒤 커밋한다.** 쓰기가 반쯤 성공한 바이트를 업무 데이터가
  참조하는 상황을 만들지 않는다.
- **fail-closed.** 검사 불가·판정 불확실은 "아마 괜찮겠지"가 아니라 계속 격리다. v1에는
  사람이 수동으로 안전 해제하는 기능 자체가 없다(단계 2로 연기).

**URL만 있고 바이트가 없는 첨부**는 특히 조심스럽게 다룬다. 사용자가 입력한 임의 URL을
서버가 가져오면 SSRF(내부망 주소를 대신 긁게 만드는 공격)가 된다. 그래서 검증된
`source_system`별 커넥터만, allowlist 호스트·TLS·리다이렉트 제한·DNS IP 검사·타임아웃·50 MiB
상한 아래에서 가져오고, 결과는 역시 quarantine으로만 들어간다. 취득 실패·변경·소실은
번들의 **차단 이슈**가 된다.

### 4.3 `document_bundle` — 이 설계에서 가장 중요한 개념

번들은 **"이 공고를 분석할 때 쓸 문서 목록을 지금 이 상태로 확정한다"**는 선언이다.

```
status: draft  →  (담당자 확인)  →  ready
```

`ready`가 되는 순간 `document_bundle_item`에 그 시점의 모든 값이 **복사**된다.

```
document_bundle_item
  bundle_id, document_version_id                    ← 무엇을
  content_sha256, size_bytes, detected_mime         ← 그때 어떤 바이트였고
  original_filename, source_url, source_kind        ← 어디서 왔고
  role_at_confirmation                              ← 그때 역할이 뭐였고
  is_current_at_confirmation                        ← 그때 최신본이었고
  safety_status_at_confirmation                     ← 그때 안전 판정이 뭐였고
  structure_id_at_confirmation, structure_payload_sha256  ← 어떤 구조화 결과였는지
```

컬럼 이름에 `_at_confirmation`이 붙은 게 눈에 띌 것이다. 이것들은 정규화 관점에서 보면
**의도적인 비정규화(denormalization)**다. `document_version`을 조인하면 알 수 있는 값을
왜 복사하는가?

조인하면 **지금** 값이 나오기 때문이다. 우리가 알아야 하는 건 **그때** 값이다.

```
1월 10일  bundle A ready — 제안요청서 v1 (sha=aaa) 포함
1월 12일  발주처가 제안요청서 개정 → document_version v2 (sha=bbb) 등록, v1은 is_current=false
1월 15일  "1월 10일 보고서는 뭘 근거로 했나?"

  조인 방식  → "제안요청서 (현재 v2, sha=bbb)"   ← 거짓말
  스냅샷 방식 → "제안요청서 v1, sha=aaa"          ← 사실
```

이 패턴은 회계·주문 시스템에서 흔하다. 주문 시점 가격을 `order_item`에 복사해두고
상품 테이블의 현재 가격을 조인하지 않는 것과 같다.

번들의 나머지 규칙:

- **차단(blocking) 이슈가 남아 있으면 `ready` 전환을 거부한다.** 바이트를 못 가져온 첨부,
  격리 상태 파일, 구조화 실패가 여기 해당한다. 확인 시점에 `issues_snapshot`으로 고정한다.
- **`ready` 전환은 한 트랜잭션에서** bundle/document/structure를 잠그고 수행한다. 확인하는
  도중에 문서가 바뀌면 스냅샷이 찢어진다.
- **item은 절대 UPDATE/DELETE하지 않는다.** 잘못 확정했으면 새 document_version을 만들고
  **새 번들**을 만든다. `supersedes_bundle_id`로 이전 번들을 가리킨다.
- 나중에 안전 상태가 나빠지면(예: 새 시그니처로 악성 판정) 과거 스냅샷은 그대로 두되,
  **신규 분석과 원문 열람은 막고** 과거 보고서에는 경고를 띄운다. 과거를 조작하지 않으면서
  현재를 보호하는 방식이다.

---

## 5. 계층 ③④⑤ — 지식·분석·운영

### 5.1 지식 3개 테이블 — 판단 기준도 버전이다

```
profile_version          "우리 회사가 무엇을 할 수 있는가" (immutable)
   └─ profile_evidence   "그 주장의 증빙 문서 어디"
analysis_policy_version  "어떤 모델에 어떤 prompt로, 어떤 검증 규칙으로" (immutable)
```

발상 자체가 중요하다. 분석 결과가 달라졌을 때 원인은 셋 중 하나다 — 문서가 바뀌었거나,
회사 역량 정보가 바뀌었거나, 분석 규칙이 바뀌었거나. 셋 다 버전으로 고정해두지 않으면
원인을 영영 못 가린다. `deep_review` 행이 이 셋의 ID를 전부 들고 있는 이유다.

`profile_evidence`는 회사 역량 주장에도 근거를 요구한다. "우리는 이 분야 실적이 있다"는
문장 하나하나가 `fact_key`로 식별되고, 어느 파일 어디에 그 증빙이 있는지 `locator`로
가리킨다. CLAUDE.md의 "확인되지 않은 회사 역량·자격·실적을 추정하지 않는다"가 여기 대응된다.

**v1에는 프로필·정책을 웹에서 편집하는 기능이 없다.** 변경은 서버 CLI import + 새 버전
생성으로만 가능하다. 게다가 import 후보는 고정 표본에서 **필수 항목 재현율 80% 이상,
사람 판정 일치율 70% 이상, 근거 부족 오판율 10% 이하**를 통과해야 active로 지정될 수 있고,
그 측정 결과와 표본 해시가 정책 payload의 검증 metadata에 함께 들어간다. 판단 기준을 바꾸는
일에는 측정된 근거가 필요하다는 뜻이다.

### 5.2 분석 11개 테이블 — 실행에서 결정까지

```
deep_review                    분석 1건 (공고 × 번들 × 프로필 × 정책 조합에 유일)
   └─ deep_review_attempt      실행 시도 (실패하면 2회차, 3회차…)
        └─ deep_review_stage   3단계 × 시도
             └─ claim          모델이 만든 주장 하나하나
                  └─ claim_evidence ──> evidence_ref   근거 인용
   └─ report_revision          보고서 스냅샷 (machine → human 수정 체인)
        └─ validation_run      결정적 검증 실행
             └─ validation_check   개별 검사 항목
        └─ final_opinion       사람의 최종 판단
```

**3단계 분석**은 다음과 같다.

1. `requirements_and_evaluation` — 요구사항과 평가 기준
2. `delivery_risk_economics` — 수행 위험과 경제성
3. `synthesis_and_validation` — 종합과 자체 검증

여기 중요한 함정 방지 규칙이 있다. **"3단계"가 "3개의 거대 prompt"를 뜻하지 않는다.**
한 stage 행 아래에서 문서·요구사항 단위의 작은 slice로 여러 번 호출한다. 요구사항 ID와
locator는 모델 호출 **전에 결정적으로 먼저 고정**하고, slice별 결과는 스키마 검증 후 병합한다.
`invocation_metadata`가 호출별 입력 slice 해시·모델/prompt 해시·토큰·지연·오류를 배열로
보존하는 이유다. 원문 전체를 한 번에 던지면 모델이 어디를 봤는지 추적할 수 없고, 컨텍스트
한계에서 조용히 잘린다.

모델 원응답은 암호화된 임시 객체로 최대 90일 보존하고, stage의 응답 해시·structured output·
실행 metadata는 계속 남는다. 원문은 사라져도 "무엇이 오갔는지"의 증거는 남는 구조다.

**`claim`의 타입별 요구사항**이 이 시스템의 사실성 장치다.

| claim_type | 반드시 있어야 하는 것 |
|---|---|
| `fact` | evidence (원문 인용) |
| `calculation` | `formula` + 입력값들의 evidence |
| `inference` | `premise_claim_ids`(같은 review 안의 전제 claim) + evidence |
| `opinion` / `unknown` | 사실 주장으로 취급하지 않음 — 모른다는 것을 명시적으로 남김 |

`premise_claim_ids`는 저장 전에 **순환(cycle) 검사와 소속 검사**를 통과해야 한다. A가 B를
근거로, B가 A를 근거로 삼는 자기 정당화를 막는다.

`claim.status`는 `supported | unsupported | conflicting | unknown`이다. 근거를 못 댄 주장은
지워지지 않고 `unsupported`로 남아 사람에게 보인다. **자동 보정하지 않는다**는 규칙의 구현이다.

**보고서는 델타가 아니라 전체 스냅샷이다.**

```
report_revision seq=1  origin='machine'  created_by_name=NULL   parent=NULL
report_revision seq=2  origin='human'    created_by_name='김철수' parent=(seq1)  change_reason='예산 수치 정정'
report_revision seq=3  origin='human'    created_by_name='이영희' parent=(seq2)  change_reason='…'
```

각 행은 완전한 `report_payload` JSON을 통째로 들고 있다. 델타 오버레이를 합성해서 보여주는
방식이 아니다. 저장 공간은 더 쓰지만, "3주 전 승인 시점의 보고서"를 재구성하는 데 합성
로직이 필요 없다 — 그 행 하나만 읽으면 된다. 합성 로직에 버그가 생기면 과거가 소급해서
바뀌는데, 그건 감사 대상 시스템에서 일어나면 안 되는 일이다.

DB CHECK로 강제되는 것: machine origin은 `created_by_name`이 null, human origin은 non-null이고
parent와 change_reason이 필수다. 사실관계를 바꾸는 수정은 사유와 근거 링크가 필요하고
**새 validation run을 만든다**.

**시스템 추천과 사람 최종 의견은 다른 어휘를 쓴다.** 이건 의도적이다.

```
system recommendation:  추진 검토 | 조건부 추진 검토 | 보류 | 검토 종료
final opinion:          추진      | 조건부 추진      | 보류 | 검토 종료
```

"검토"라는 단어가 붙고 안 붙고의 차이로 **누가 결정했는지가 어휘 자체에 남는다.** 모델이
"추진"이라고 말할 수 없고, 사람이 "추진 검토"라고 말할 수 없다. CLAUDE.md의 "적합성 등급,
참여 준비 상태, 심층 검토 추적 선택, 최종 Go/No-Go를 서로 대신하지 않는다"가 여기 대응된다.

**검증 실패 시 강제 인지(acknowledgement).** 검증이 실패했는데도 사람이 판단을 내리려면,
`acknowledged_validation_failure = TRUE`이고 `reason`이 비어 있지 않아야 한다. 애플리케이션
코드가 아니라 **DB CHECK 제약**이 이걸 막는다.

### 5.3 운영 3개 테이블

```
work_job             작업 큐 (수집·구조화·분석)
idempotency_record   같은 요청 두 번 실행 방지
audit_event          누가 무엇을 했는지 안전한 metadata만
```

`work_job`의 워커 패턴은 표준적이지만 정확히 알아둘 가치가 있다.

```sql
-- 1) 짧게 잡아채기: 다른 워커가 잡은 행은 건너뛴다
SELECT * FROM work_job
 WHERE status='queued' AND scheduled_at <= now()
 ORDER BY priority DESC, scheduled_at
 FOR UPDATE SKIP LOCKED LIMIT 1;
-- 2) lease_owner, lease_expires_at 설정, lease_fence 증가
```

`FOR UPDATE SKIP LOCKED`는 여러 워커가 같은 작업을 중복으로 집는 것을 막는다.
`lease_fence`(단조 증가 정수)는 더 미묘한 문제를 막는다 — **좀비 워커**다.

```
워커 A가 job을 잡음 (fence=5) → 네트워크 단절 → lease 만료
워커 B가 같은 job을 잡음 (fence=6) → 분석 진행
워커 A가 되살아나서 "내 결과 저장할게" → fence=5로 시도 → 거부됨
```

stage와 report 저장은 "현재 job/owner/fence가 일치할 때만" 쓰는 조건부 SQL로 수행한다.
이 기법의 이름은 **fencing token**이다.

`idempotency_record`는 재실행 피해가 있는 mutation(업로드, 번들 확정, 분석 생성·재시도,
보고서 수정, 최종 의견)에만 붙는다. 유일 범위는
`(claimed_name, operation, aggregate_type, aggregate_id, request_id)`이고, request 해시에는
canonical metadata와 업로드 바이트 해시가 들어간다. 같은 `request_id`로 다시 오면 저장된
응답을 그대로 돌려준다 — 네트워크 타임아웃 후 브라우저가 재시도해도 최종 의견이 두 번
기록되지 않는다. `response_snapshot`에는 **원문 바이트나 비밀을 넣지 않는다.**

job 상태 전이는 별도 이벤트 테이블 없이 `audit_event`에 안전한 metadata로만 기록한다.

---

## 6. 시나리오로 따라가기

말로 된 규칙보다 흐름 하나가 이해에 빠르다.

### 6.1 정상 경로

```
[1] 수집
    notice(id=1042) 등록, attachment 3건 (제안요청서.pdf, 과업지시서.hwp, 붙임.zip)

[2] 바이트 확보
    각 파일 → quarantine 기록 → sha256 재검증 → MIME/ClamAV 검사 통과
    → content_object 3행 (sha256이 정체성)
    → content_object_location 3행 (source namespace, object_version_id 기록)
    → content_scan 3행 (clean)

[3] 업무적 의미 부여
    document_version 3행 생성
      (notice_id=1042, role='제안요청서', version=1, is_current=true, safety_status='clean')

[4] 구조화
    work_job(job_type='structure') → 격리 문서 처리기 호출
    → document_structure 3행 (extractor_version 기록)
    → 전체 JSON은 객체 스토리지, document_block 약 1,200행은 DB에 투영

[5] 번들 확정
    담당자가 3건을 검토, blocking issue 없음 확인 → ready
    → document_bundle(status='ready', revision=1)
    → document_bundle_item 3행에 그 시점 값 전부 복사(_at_confirmation)

[6] 분석 요청
    deep_review 생성
      notice_id=1042, bundle_id=B, profile_version_id=P7, policy_version_id=Q3
      effective_grade_at_start='B', status='queued'
    → work_job(job_type='deep_review') → deep_review_attempt(sequence=1, status='queued')

[7] 워커 실행
    stage 1 requirements_and_evaluation
      요구사항 ID와 locator를 먼저 결정적으로 고정
      slice 단위로 Qwen 호출 12회 → invocation_metadata에 12개 항목 기록
      → structured_output 저장, 원응답은 암호화 객체(90일)
      → claim 34행, evidence_ref 51행, claim_evidence 연결
    stage 2 delivery_risk_economics   (동일 패턴)
    stage 3 synthesis_and_validation  (동일 패턴)

[8] 보고서
    report_revision(sequence=1, origin='machine', created_by_name=NULL)
      report_payload = 완전한 보고서 JSON, report_sha256 기록
    → report_revision_evidence로 인용된 근거 연결

[9] 검증
    validation_run(sequence=1) → validation_check 여러 행
      근거 인용이 실제 원문과 일치하는가, 계산식이 맞는가, unsupported claim 비율은…
    → status='passed'

[10] 사람 결정
    final_opinion(sequence=1, value='조건부 추진', claimed_name='김철수',
                  validation_run_id=V1, validation_status_at_opinion='passed',
                  acknowledged_validation_failure=false, reason='…')
```

### 6.2 재시도 — 모델 호출이 stage 2에서 터졌다

```
deep_review_attempt(sequence=1, status='failed')      ← 그대로 남는다
deep_review_attempt(sequence=2, status='queued')      ← 새 시도
```

1회차의 stage·claim·evidence는 **지워지지 않는다.** "왜 실패했는가"를 나중에 봐야 하기
때문이다. partial unique index가 `queued|running` attempt를 review당 하나로 제한하므로
동시에 두 시도가 돌아갈 수는 없다.

### 6.3 사람 수정 — 예산 수치가 잘못 뽑혔다

```
report_revision(seq=1, origin='machine')  ← 그대로
report_revision(seq=2, origin='human', parent=seq1,
                created_by_name='김철수', change_reason='예산 표 오독 정정')
  → 사실관계 변경이므로 근거 링크 필수
  → validation_run(sequence=2)가 새로 생성됨
```

seq=1은 영원히 남는다. "모델이 원래 뭐라고 했는가"와 "사람이 무엇을 고쳤는가"가 둘 다 보인다.

### 6.4 검증 실패인데도 결정해야 한다

```
validation_run(sequence=2, status='failed')
final_opinion(value='보류',
              validation_run_id=V2,
              validation_status_at_opinion='failed',   ← 실제 상태와 복합 FK로 일치 강제
              acknowledged_validation_failure=TRUE,     ← 없으면 CHECK 위반
              reason='근거 부족 항목 3건 인지, 마감 임박으로 보류 결정')
```

`(validation_run_id, validation_status_at_opinion)` 복합 FK가 걸려 있어서 "실제로는
failed였는데 passed였다고 적기"가 **DB 수준에서 불가능**하다.

### 6.5 문서가 개정됐다

```
발주처가 제안요청서 개정본 배포
  → document_version(version=2, replaces_document_version_id=v1, is_current=true)
  → 기존 v1은 is_current=false, 하지만 삭제되지 않음
  → 새 document_bundle(revision=2, supersedes_bundle_id=B1) 생성 후 ready
  → 새 deep_review 생성 (notice×bundle×profile×policy 조합이 다르므로 unique 통과)

기존 deep_review와 그 보고서는 그대로 유효하다.
"1월 10일 판단은 개정 전 문서 기준"이라는 사실이 데이터에 남아 있다.
```

---

## 7. 여기서 배울 설계 기법 7가지

이 스키마는 몇 가지 잘 알려진 패턴의 조합이다. 이름을 알아두면 다른 프로젝트에서도 쓴다.

**① Content-addressed storage**
`content_object.sha256`이 정체성. Git, Docker layer, IPFS가 같은 원리. 중복 제거가 공짜로
따라오고, "이 파일이 그 파일이 맞나"가 항상 검증 가능해진다.

**② Snapshot / pinning (의도적 비정규화)**
`document_bundle_item`의 `_at_confirmation` 컬럼들. 정규화 이론은 "조인해서 가져와라"라고
하지만, 이력이 중요한 도메인에서는 **그때 값**을 복사해야 한다. 주문 시점 가격, 계약 시점
약관, 승인 시점 문서가 전부 같은 패턴.

**③ Append-only + revision chain**
`report_revision`이 parent를 가리키는 링크드 리스트. 이벤트 소싱의 사촌뻘이지만, 델타가
아니라 전체 스냅샷을 저장해서 재구성 로직 자체를 없앴다.

**④ Composite FK로 범위(scope) 강제 — 이 설계의 가장 독특한 부분**

문제: `evidence_ref`가 **다른 분석의 근거**를 실수로 가리키는 것을 어떻게 막나?

```
-- 단순 FK로는 이걸 못 막는다
evidence_ref.deep_review_id → deep_review.id        ✓
evidence_ref.bundle_id      → document_bundle.id    ✓  (아무 번들이나 가리킬 수 있음!)
```

해법은 부모에 **불필요해 보이는 unique**를 만들고, 자식이 복합 FK로 참조하는 것이다.

```
deep_review에 UNIQUE(id, bundle_id)                    ← id가 이미 PK인데도!
evidence_ref에 FK(deep_review_id, bundle_id)
                 → deep_review(id, bundle_id)

결과: evidence_ref는 자기가 속한 deep_review가 실제로 쓴 번들만 가리킬 수 있다.
```

같은 기법이 여러 겹으로 쌓여 있다.

```
FK(bundle_id, document_version_id, structure_id)
   → document_bundle_item(bundle_id, document_version_id, structure_id_at_confirmation)
```

→ 근거는 **ready 스냅샷 안의 문서**만 가리킬 수 있다. 확정 후에 추가된 문서를 근거로 쓰는
것이 DB 수준에서 불가능하다.

```
FK(validation_run_id, validation_status_at_opinion) → validation_run(id, status)
```

→ 최종 의견이 기록한 검증 상태가 실제 상태와 다를 수 없다.

일반적 이름은 **composite/scoped foreign key**다. 핵심 통찰은 이것이다:
**애플리케이션 코드로 검사하는 규칙은 언젠가 우회된다.** 마이그레이션 스크립트, 데이터
수정용 일회성 쿼리, 새로 짠 엔드포인트가 검사를 건너뛴다. 스키마에 넣으면 우회할 방법이 없다.

**⑤ Partial unique index로 상태 기반 유일성**

```sql
CREATE UNIQUE INDEX uq_work_job_active
  ON work_job (job_type, aggregate_type, aggregate_id)
  WHERE status IN ('queued','running');
```

"진행 중인 작업은 대상당 하나"를 표현한다. 완료된 작업은 몇 개든 쌓여도 된다. 조건 없는
unique로는 이런 규칙을 못 쓴다. `deep_review_attempt`의 활성 시도 제한,
`attachment`의 provider 중복 방지도 같은 방식이다.

**⑥ Fencing token (`lease_fence`)**
분산 락이 만료된 뒤 좀비 워커가 옛날 결과를 덮어쓰는 것을 막는 단조 증가 정수.
Martin Kleppmann의 *Designing Data-Intensive Applications*에 나오는 그 패턴이다.

**⑦ Idempotency key**
`(claimed_name, operation, aggregate_type, aggregate_id, request_id)` + request 해시.
결제 API가 쓰는 것과 같은 구조. 재시도가 안전한 mutation에만 붙인다는 절제도 함께 배울 점이다.

---

## 8. 삭제 정책 — 왜 전부 RESTRICT인가

기본값이 `RESTRICT`/`NO ACTION`이다. `CASCADE`는 딱 두 군데만 있다.

| 관계 | 정책 | 이유 |
|---|---|---|
| run/notice → 업무 이력 | RESTRICT | 공고를 지우면 판단 이력이 통째로 사라진다. archive만 허용 |
| judgment → 판정 detail | CASCADE | "판정 전체 교체"라는 명시적 연산일 때만 |
| review → verification_answer | CASCADE | review PUT 전체 교체일 때만 |
| attachment → document_version | SET NULL | document_version이 출처 스냅샷을 이미 갖고 있어 고아가 되지 않는다 |
| content/document/structure/bundle → 계보 | RESTRICT | 정본 계보는 끊지 않는다 |
| profile/policy → deep_review | RESTRICT | 분석이 참조 중인 기준을 못 지운다 |
| deep_review → attempt/claim/report/… | RESTRICT | 분석 산출물은 지우지 않는다 |

일반적인 CRUD 앱은 `CASCADE`를 편의로 쓴다. 여기서는 반대다. **삭제가 조용히 번지는 것이
가장 위험한 일**이므로, 지우려면 자식부터 명시적으로 처리하게 만들어서 "지금 뭘 지우는지"를
개발자가 자각하게 한다.

v1은 UPDATE/DELETE 금지를 테이블별 grant나 trigger가 아니라 **서비스 경계 + DDL 제약 +
회귀 테스트**로 강제한다. 실제 위반 위험이 확인되면 그때 trigger나 세분 role을 추가한다.
DB role은 `bidops_owner`(마이그레이션), `bidops_app`, `bidops_worker`, `bidops_ro_backup`
네 개 경계만 둔다.

---

## 9. 자주 하는 오해

**"보고서 고치면 되는 거 아닌가요?"**
아니다. `UPDATE report_revision`은 하지 않는다. 새 revision을 만든다. 코드 리뷰에서
report/claim/evidence/validation/opinion에 대한 UPDATE·DELETE가 보이면 그건 버그다.

**"근거는 그냥 페이지 번호 문자열로 저장하면 안 되나요?"**
`evidence_ref`가 `structure_id`까지 들고 있는 이유는, 페이지 번호는 추출기 버전이 바뀌면
달라질 수 있기 때문이다. "어떤 구조화 결과의 몇 페이지"여야 재현된다.

**"같은 공고를 두 번 분석하려는데 unique 제약에 걸립니다."**
`unique(notice_id, bundle_id, profile_version_id, policy_version_id)`다. 정말 같은 입력이면
기존 분석을 보면 되고, 다시 돌리고 싶으면 새 **attempt**를 만드는 것이다. 입력 중 하나라도
바뀌었다면(문서 개정 → 새 번들, 정책 갱신 → 새 policy version) 자연히 새 deep_review가 된다.

**"stage가 3개니까 prompt도 3개죠?"**
아니다. 5.2에서 설명한 대로 stage 안에서 slice 단위 다중 호출이 정상이다. 거대 prompt
하나는 금지 사항으로 명시돼 있다.

**"이름이 같으면 같은 사람 아닌가요?"**
아니다. 3.1 참고. 인증이 없으므로 동일인 판정을 하지 않는다.

**"OCR이 글자를 잘못 읽었는데 DB에서 고치면 안 되나요?"**
v1에는 인앱 OCR 교정 기능이 없다. `미확인`으로 남기거나, 담당자가 정정 파일을 **새
document version**으로 다시 등록한다.

**"파일을 지우고 싶은데요."**
일반 업무 흐름에서 attachment를 물리 삭제하지 않는다. `retired_at`, `retired_reason`,
`retired_by_name`으로 은퇴 처리한다.

---

## 10. 실제 구현과의 대조

설계 문서와 코드가 실제로 일치한다. 확인 지점은 다음과 같다.

| 항목 | 위치 |
|---|---|
| ORM 모델 | `web/backend/app/models.py` |
| 최초 스키마 마이그레이션 | `web/backend/alembic/versions/0001_lean_v1_postgresql.py` |
| 심층 검토 관련 테이블 수 | 38개 (레거시 13 + 문서 8 + 지식 3 + 분석 11 + 운영 3) |
| `models.py`의 전체 테이블 수 | 50개 |

차이 12개는 ERD 범위 밖의 **선별 런타임**(`screening_execution`, `screening_attempt`,
`quality_gate`, `quality_gate_evaluation`, `quality_gate_review`, `screening_policy`,
`company_profile_snapshot`, `schedule_setting`, `schedule_reservation`, `schedule_execution`,
`always_on_state`, `screening_audit_event`)이다. `deep-review-erd.md`는 심층 검토 경계만
다루므로 여기 없는 게 정상이다. 혼동하지 말 것.

코드에서 이 문서의 주장을 직접 확인해볼 만한 지점:

```python
# app/models.py — 근거의 범위를 복합 FK로 강제 (7장 ④)
ForeignKeyConstraint(
    ["bundle_id", "document_version_id", "structure_id"],
    [_table("document_bundle_item.bundle_id"),
     _table("document_bundle_item.document_version_id"),
     _table("document_bundle_item.structure_id_at_confirmation")],
    name="fk_evidence_document_bundle_scope"),

# app/models.py — 검증 실패 시 인지 강제 (6.4)
CheckConstraint(
    "(validation_status_at_opinion = 'passed' OR "
    " (acknowledged_validation_failure = TRUE AND reason IS NOT NULL "
    "  AND length(trim(reason)) > 0))",
    name="ck_final_opinion_failed_ack"),

# app/models.py — 활성 시도는 review당 하나 (7장 ⑤)
Index("uq_deep_review_attempt_active", "deep_review_id", unique=True,
      postgresql_where=column("status").in_(["queued", "running"])),
```

문자열 + CHECK 조합을 Python Enum 대신 쓴 이유도 `models.py` 주석에 적혀 있다. 운영 도구나
미래의 워커가 Python을 거치지 않고 DB에 쓸 수 있으므로, 어휘 강제는 DB에 있어야 한다.

---

## 11. 용량과 한계

| 항목 | 값 |
|---|---|
| 계획 부하 | 월 100 공고, 800 document version, 32,000 페이지, 약 960,000 block |
| 시작 사양 | PostgreSQL 4 vCPU / 16 GiB / 암호화 NVMe 200 GiB, MinIO usable 1 TiB |
| 목표 | RPO 4시간, RTO 8시간 |
| 재평가 트리거 | disk free 30% 미만, block 2천만 행, 핵심 쿼리 p95 500 ms 초과 |
| 필수 extension | 없음 (UUID는 애플리케이션에서 생성) |

`pg_trgm`, 벡터 검색, 한국어 전문검색, partitioning은 **실측 후** 검토다. 초기 검색은
B-tree/partial/expression 인덱스와 제한된 `ILIKE`만 쓴다. 성능 문제가 실제로 생기기 전에
확장을 도입하지 않는다는 판단이다.

백업은 매일 full base backup + 연속 WAL archive, 객체는 최소 4시간 간격으로 **별도 host·
credential·장애 도메인**의 저장소에 복제한다. 복구는 객체를 먼저 복원한 뒤 PostgreSQL을
복원하고 active location의 SHA-256을 검증하는 순서다.

단계 2로 명시적으로 미룬 것들(원문 13장): Langfuse trace UI, 프로필·정책 관리 UI,
프로필 URL capture, 수동 악성 해제, 인앱 OCR 교정, review 간 claim diff, 범용 retention
control plane, backup drill 테이블, SSO identity schema, 한국어 전문검색·벡터 검색.

**이 목록을 "편의상 미리 구현"하지 않는 것이 규칙이다.** 필요해지면 별도 승인과 새
마이그레이션으로 추가한다.

---

## 12. 한 장 요약

```
이 DB가 답하는 질문:
  "누가, 언제, 어떤 문서를, 어떤 기준으로 분석해서, 어떤 근거로, 무엇을 결정했는가"
  — 그리고 그 답이 6개월 뒤에도 똑같이 재구성되는가

핵심 장치 5개:
  1. sha256으로 바이트를 식별한다              (거짓 파일 불가)
  2. 분석 시작 시 입력을 스냅샷으로 박제한다     (사후 변경 무영향)
  3. 결과는 지우거나 고치지 않고 새 행으로 쌓는다 (이력 손실 불가)
  4. 근거 없는 주장은 unsupported로 남는다       (지어내기 불가)
  5. 범위 규칙을 복합 FK로 스키마에 박는다        (코드 우회 불가)

기억할 금지 사항 3개:
  - report/claim/evidence/validation/opinion을 UPDATE·DELETE하지 않는다
  - 시스템 추천 어휘와 사람 최종 의견 어휘를 섞지 않는다
  - stage 3개를 거대 prompt 3개로 구현하지 않는다
```

궁금한 게 남으면 순서대로 본다: `deep-review-erd.md`(계약) → `web/backend/app/models.py`(구현)
→ `docs/business-rules.md`(업무 규칙) → `docs/contracts.md`(외부 계약).
