# BidOps Agent 작업 지침

BidOps Agent는 기획·사업개발 담당자가 나라장터 공고를 빠짐없이 모으고, 회사 적합성을 선별한 뒤 첨부문서 기반 심층 검토까지 수행하도록 돕는 사내 의사결정 지원 시스템이다. Python 기반 파이프라인과 FastAPI·React 관리 화면으로 구성되며, 자동 입찰·외부 연락·최종 참여 결정은 담당자의 몫으로 남긴다.

## 프로젝트 구조

```text
bidops-agent/
├── CLAUDE.md                         ← Claude Code 작업 진입점
├── AGENTS.md                         ← Codex 작업 진입점
├── docs/
│   ├── architecture.md               ← 목표 구성과 데이터 흐름
│   ├── business-rules.md             ← 선별·심층 검토 도메인 규칙
│   ├── security.md                   ← 사내망 접근·감사·민감정보 정책
│   ├── standards.md                  ← 구현과 검증의 강제 규칙
│   ├── engineering-notes.md          ← 재발하기 쉬운 함정과 대응법
│   ├── operations.md                 ← 설치·실행·검증·백업 절차
│   ├── contracts.md                  ← 웹 API와 파이프라인 산출물 계약
│   ├── agent-runtime.md              ← 판정 에이전트 실행 경계와 모델 호출 설계
│   ├── scheduling.md                 ← 정기 실행·회차 경계·실패 처리 설계
│   ├── model-quality-gate.md         ← 모델 품질 측정과 활성화 게이트
│   └── tracking/
│       ├── status.md                 ← 구현·검증 현황과 다음 순서
│       ├── findings.md               ← 당장 해결하지 못한 문제
│       ├── runtime-design-validation.html ← 판정 런타임 설계 검증 결과
│       └── decisions/
│           ├── index.md              ← 기술·운영 결정 목록
│           └── NNNN-<slug>.md         ← 개별 결정과 대안·결과
├── skills/
│   ├── bidops-collect/AGENTS.md       ← 수집·정규화·표본 선정 규칙
│   ├── bidops-screen/AGENTS.md        ← 1차 판정 산출물 규칙
│   └── bidops-report/AGENTS.md        ← 결정적 보고서 렌더링 규칙
└── web/
    ├── AGENTS.md                      ← 컨테이너 조립·통합 검증 규칙
    ├── backend/AGENTS.md              ← API·DB·적재·파일 처리 규칙
    └── frontend/AGENTS.md             ← 관리 화면 구현·검증 규칙
```

## 최상위 불변 조건

- 확인되지 않은 회사 역량·자격·실적과 공고 사실을 추정해 채우지 않는다. `unknown`은 결함이 아니라 검증 대기 상태로 보존한다.
- 1차 등급과 참여 준비 상태를 섞지 않는다. 자격 미확인만으로 등급을 낮추거나, 적합성이 높다는 이유로 자격을 확인 완료 처리해서는 안 된다.
- 모델이 만든 숫자·요구사항·근거는 원문 위치와 연결하고 결정적 검증을 통과시킨다. 실패한 결과는 사람 검토로 보내며 자동 보정하지 않는다.
- 기존 파이프라인 스크립트와 산출물 계약은 기준선으로 유지한다. 새 기능은 파일 계약과 명시적 어댑터를 통해 연결한다.
- 시스템은 참여 판단을 보조할 뿐 입찰 제출, 발주처 연락, 최종 Go/No-Go 결정을 자동 실행하지 않는다.

## 작업 전 확인

- 모든 변경 전에 `docs/standards.md`, `docs/engineering-notes.md`, 수정 대상 모듈의 `AGENTS.md`를 읽는다.
- 등급·준비 상태·심층 검토 단계·피드백 필드를 바꾸기 전에는 `docs/business-rules.md`에서 상태 조합과 실패 처리를 확인한다.
- 데이터베이스나 적재기를 바꾸기 전에는 불변 회차, 부분 산출물 경고, DB 정본 리뷰의 세 메커니즘을 먼저 확인한다.
- 첨부 업로드·변환·다운로드·외부 모델 전송을 바꾸기 전에는 `docs/security.md`의 경로 격리, 감사 대상, 건별 외부 전송 승인을 확인한다.
- 파이프라인 JSON/YAML 또는 REST 응답을 바꾸기 전에는 `docs/contracts.md`의 소비자 계약과 버전 규칙을 확인한다.
- 스케줄·판정 에이전트·정책 버전을 바꾸기 전에는 `docs/scheduling.md`, `docs/agent-runtime.md`, `docs/model-quality-gate.md`에서 회차 경계·호출 경계·품질 게이트를 확인하고, `docs/business-rules.md`와 `docs/contracts.md`의 상태·버전 계약을 함께 확인한다.
- Qwen 프롬프트나 검증기를 바꾸기 전에는 `docs/engineering-notes.md`의 대형 단일 프롬프트 실패 사례와 55개 요구사항 계수 사례를 확인한다.

## 문제 보고 경로

첨부 원문의 프로젝트 경로 이탈, API 키·회사자료의 로그/응답 노출, 승인 없는 OpenAI 전송, 회차 원본 또는 기존 리뷰의 덮어쓰기, 모델 근거가 원문과 다른데 통과한 경우는 작업을 멈추고 사용자에게 즉시 알린다. 그 밖에 현재 작업 범위에서 해결할 수 없는 구조 문제는 재현 조건·영향 범위·지금 해결할 수 없는 이유를 `docs/tracking/findings.md`에 기록한다.
