# 백엔드 모듈 작업 규칙

## 책임

이 모듈은 FastAPI REST 계약, SQLAlchemy·Alembic, PostgreSQL 정본, MinIO 객체, 회차 적재, 리뷰, 판정 실행, 문서 준비, 심층 검토, 보고서·근거 조회, scheduler와 worker 상태 전이를 소유한다. 원천 수집·판정 스크립트의 업무 규칙과 React 표현은 여기서 복제하지 않는다.

## 경계

- 파이프라인은 versioned file과 subprocess로 호출한다. 내부 script 함수를 서비스로 import하거나 같은 판정 규칙을 다시 구현하지 않는다.
- DB row를 그대로 REST 응답으로 노출하지 않는다. 명명된 Pydantic request/response와 안전한 오류 코드를 사용한다.
- 회사 프로필 조회는 승인된 불변 version·digest에 묶인 구조화 항목·`unknown` projection만 반환한다. filesystem source, source line, raw block·raw text, 원문 예외 문자열을 schema에 넣지 않는다.
- frontend가 DB, run 디렉터리, 객체 key를 직접 읽게 하지 않는다.
- model client와 문서 converter에 광범위 DB session이나 임의 filesystem 권한을 주지 않는다.
- 사용자 파일명으로 저장 경로를 만들지 않는다. 허용 namespace, 서버 생성 key, symlink·path escape 검사를 사용한다.

## DB와 실행 불변 조건

- PostgreSQL 17 `bidops` schema가 운영 정본이다. SQLite는 isolated test와 one-time import에만 사용한다.
- 앱 startup은 Alembic head와 필수 storage를 확인할 뿐 migration, `create_all`, policy·portal seed, 활성화를 수행하지 않는다.
- run, policy, profile, document version, model binding, report revision, final opinion은 불변 또는 append-only다. 재실행은 새 ID와 관계를 만든다.
- 리뷰 적재 뒤에는 DB가 정본이다. YAML 재적재로 기존 리뷰를 덮지 않는다.
- `null`, 0, 빈 문자열, 계산 불가를 직렬화나 집계에서 합치지 않는다.
- active screening slot과 analysis concurrency는 1이다. queue는 FIFO이고 stale 실행은 중단으로 닫으며 자동 resume하지 않는다.
- 핵심 식별자·등급·준비 상태가 없는 판정은 적재하지 않는다. 비핵심 과거 누락은 실제 값과 경고만 저장한다.

## 첨부와 심층 검토

- upload는 허용 형식·크기, 서버 생성 key, 악성코드 검사, quarantine, 객체 version을 검증한다. 요청 실패 때 해당 요청이 만든 임시 객체와 DB transaction을 정리한다.
- document bundle confirm은 최신 document version, clean scan, immutable structure snapshot을 같은 fence에서 확인한다.
- document metadata 변경은 notice → latest bundle → document 순서로 잠그고 기대 version과 hash를 재검증한다.
- 심층 검토는 고정 bundle, profile, policy, model reference만 사용한다. live attachment나 변경된 profile을 중간에 다시 읽지 않는다.
- 모델 claims, 숫자, 요구사항, evidence locator는 결정적 schema·근거 검증을 통과해야 한다. 실패는 report에 표시하고 자동 보정하지 않는다.
- model response 객체는 암호화하고 DB에는 key reference, version, hash만 저장한다.

## 접근, 로그, 외부 호출

- 현재 접근 경계는 사내망이며 로그인·role authorization은 없다. 담당자 이름은 mutation 감사 표식이고 인증 성공으로 표현하지 않는다.
- 담당자 이름, prompt, 모델 응답, 공고·회사자료 원문, upload 파일명, credential, DB URL, 쿼리 문자열을 로그에 남기지 않는다.
- 로그 field는 allowlist를 사용하고 외부 예외·subprocess stderr는 저장 전에 redaction한다.
- hosted OpenAI는 운영 기본 비활성이다. 현재 Codex deep-review provider는 개발에서도 사용하지 않는다. 외부 실험은 향후 발주계획 전용 projection에서만 공개 plan metadata와 별도 승인된 최소 회사 역량 요약을 보낼 수 있다. RFP·첨부, profile 전문, evidence, 내부 review·실적은 건별 승인으로도 허용되지 않는다. 허용 projection도 개발 mode, 대상 allowlist, payload preview·승인 중 하나라도 없으면 fail closed한다.
- 사설 vLLM과 Ollama endpoint는 목적별 allowlist와 실행 binding을 사용한다. 하나의 장애를 다른 provider 자동 fallback으로 처리하지 않는다.

## API와 서비스 구현

- router는 parsing·HTTP mapping만 하고 상태 전이, idempotency, lock, storage 작업은 service에서 처리한다.
- 장시간 변환·모델 작업은 요청 안에서 기다리지 않고 202 execution/attempt와 조회 가능한 상태를 반환한다.
- mutation은 actor, idempotency 또는 기대 version, audit event를 같은 논리 transaction에 묶는다.
- error에는 안정 code와 안전한 message만 두고 내부 path, SQL, model body를 노출하지 않는다.
- 새 schema 의미는 새 version으로 추가한다. 역사 artifact importer의 관대한 처리와 현재 producer의 엄격한 처리를 섞지 않는다.

## 검증

```bash
cd web/backend && .venv/bin/pytest
```

DB 변경은 임시 PostgreSQL 17의 빈 migration, 제약, 중복 적재, rollback을 검사한다. API 변경은 정상과 404/409/422/503, idempotency, 상태 fence, actor encoding, 비밀 없는 오류를 포함한다. 첨부는 형식·크기·path escape·symlink·scan 실패·부분 정리를, 모델·worker는 timeout·잘림·schema·근거 실패·재시도·무승인 외부 호출 차단을 검사한다.
