# 제안서 초안(요구사항 대응표·절 초안·PDF) — intent

- 기능 ID: `RL-04-proposal-draft`
- 상위 항목: roadmap §RL 표 5행, ADR-0073 결정 2(G3)·개정(PDF 1차·HWP 후속), 인터뷰 E1~E4, [bid-procedure §4·§5](../../../../../1016_rootlab-redefinition/bid-procedure.md), [ui-spec §4.5](../../../../../1016_rootlab-redefinition/ui-spec.md), ux-review §5 결정 5·6
- 크기: L — 새 정책 파일(용도 `proposal`)·전송 승인 행·테이블 4개·REST 8개·전용 WorkJob/worker·Luna 호출(절당 1회)·PDF 렌더러·화면 1개. 외부 모델 호출. 착수는 RL-03 병합 뒤.
- 작성일: 2026-10-16

## 문제

참여를 결정한 뒤에도 제안서는 백지에서 시작한다. 루트랩에는 과거 제안서·표준 문구가 없고(E1·E3), 제안요청서의 요구사항 수십 개를 하나씩 읽어 "어느 절에서 어떻게 답할지"를 사람이 짜야 한다. 요구사항 누락은 평가에서 바로 감점이고, 평가위원은 요구사항 ↔ 제안서 쪽 참조표를 요구한다(bid-procedure §4 13번).

## 기대 결과

- 판정이 끝난 사업기회에서 "제안서 초안"을 누르면 제안요청서 목차(bid-procedure §5)와 회사 근거(RL-00 `confirmed` 사실)·요구사항 분석(RL-03 unit·대조)만으로 여섯 절 초안(제안 개요 · 사업수행 실적 · 수행 전략 · 요구사항 수행방안 · 운영·SLA · 수행조직)과 요구사항 대응표를 만든다. 모든 문장은 출처(요구사항 unit 또는 회사 사실)를 갖고, 출처 없는 문장은 생성하지 않는다. 가격·투입 인력 수·전략 수치는 넣지 않고 빈 자리로 남긴다.
- `/opportunities/:id/proposal`에서 절 단위로 읽고, 문장 수정·절 다시 쓰기·검토 완료를 하며, PDF로 내보낸다. PDF에도 빈 자리·제안 수치 표식과 출처가 남는다(ux-review 결정 6).
- HWP 출력은 범위 밖(후속 결정). 제출본은 사람이 만든다.

## 유즈케이스

| 유즈케이스 | 실행 방법 | 확인 기준 |
|---|---|---|
| 초안 생성 | 판정 탭 "제안서 초안"(또는 `POST /api/opportunities/{id}/proposal-requests`) | 202 → `GET …/proposal` `status=completed`, 절 6개, 요구사항 대응표에 RL-03 unit 전부(누락 0), 출처 없는 문장 0 |
| 판정 없는 사업 | 판정 `none`인 사업에서 요청 | 409 `verdict_required` |
| 문장 수정 | 절 본문 "문장 수정" → 저장 | overlay 1건 append, 생성 원문 불변, 화면·PDF에 수정본 + "수정됨" 표식 |
| 절 다시 쓰기 | "이 절 다시 쓰기" | 그 절만 새 생성(새 revision), 이전 절 보존, cap 소비 |
| 검토 완료 | 절 "검토 완료" | 절 `reviewed`, 좌측 단계 stepper 진행, 모든 절 reviewed → 초안 단계 `검토 완료` |
| PDF 내보내기 | 헤더 "PDF로 내보내기" | `GET …/proposal/export.pdf` 200 PDF, 빈 자리 노란 바탕·출처 위첨자·끝에 출처 목록·대응표 부록; 같은 내용이면 같은 sha256 |
| 금지 내용 | 생성 결과에 "원"·"명"이 붙은 가격·투입 인원 숫자 | 검증 실패 → 절 `failed`·사람 검토, 자동 보정 없음 |

## 선행·후속 기능

- 선행: `RL-03-fit-verdict`(unit·대조·판정·전송 승인 테이블·Luna 경로), `RL-00`(회사 사실), `RL-02`(제안서 탭 자리·활동 hook).
- 후속: `RL-05-gold-acceptance`(제안서 요구사항 누락 0 측정은 RL-05 범위에 넣지 않고 이 기능 T로 고정), `RL-06`(토큰 계측), HWP 출력(후속 결정).

## 영향 범위

- 모듈·컴포넌트: deep_review(`services/proposal_draft.py`·`proposal_render.py`·`proposal_validation.py`, `schemas/proposal.py`, `contracts/bidops.proposal-section.v1.json`, `policies/proposal-policy-luna-v1.json`, `routers/proposals.py`, worker dispatch `proposal-v1`), codex-runner(contract `proposal-section-v1`), 프런트 `pages/OpportunityProposalTab.tsx`·`components/proposal/*`, lifecycle 활동 hook `draft_prepared`.
- 큰 틀 문서의 절: contracts.md(REST·DB·정책·PDF), business-rules.md(제안서 초안 규칙), operations.md(승인·cap·폰트), tech-stack(PDF 렌더러·폰트 의존), ui-spec §4.5.
- 데이터·저장소: `proposal_draft`·`proposal_section`·`proposal_sentence_edit`·`proposal_export`(PDF는 MinIO 객체 `proposal-pdf`, sha256). 권한 runtime-privileges.sql(열 단위·trigger). 폰트는 이미지의 `fonts-nanum`.
- 외부 서비스·호출: Luna 절당 1회(+repair ≤1) = 6~12회/초안. PDF 렌더는 로컬.

## 제약

- (공통) feature.json constraints 전부(정책 단위 승인·건별 감사·allowlist·fallback 금지, append-only, unknown 보존).
- (기능별) 출처 없는 문장 생성 금지, 가격·투입 인력·전략 수치 금지(빈 자리로), `proposed`/`unknown` 회사 사실은 문장 근거로 쓰지 않음, 노트 본문(RL-02) 전송 금지, 운영 정보 화면 노출 금지. PDF에 표식 보존. 제출본·가격·인력 확정은 사람.

## 범위 밖

HWP 출력, 가격·투입 인력·일정표 생성, 제안발표 자료, 정량 제안서 서식 채우기(실적증명 목록은 unknown이라 빈 자리), 과거 제안서 학습, 제출 서류 체크리스트, 다국어.

## 출처 간 차이

| 차이 | 출처 A | 출처 B | 결정 |
|---|---|---|---|
| 출력 형식 | ADR-0073 결정 2 DOCX | 개정(E2) PDF 1차·HWP 후속 | PDF만. HWP는 변환기 결정 뒤 별도 기능 |
| 절 구성 | bid-procedure §5 5장(Ⅰ~Ⅴ) | ui-spec §4.5 절 탭 6개 | 화면·초안은 ui-spec 6절, 각 절이 §5의 어느 장·절에 대응하는지 표로 고정(spec) |
| 사업수행 실적 | §5 Ⅱ-3 최근 3년 실적 | 인터뷰 B1·B2 실적증명 목록 미입력(unknown) | 홈페이지 실적(confirmed)만 문장으로, 증명 가능 여부는 빈 자리 |

## 미해결 질문

| 질문 | 답이 필요한 시점 | 결정 |
|---|---|---|
| PDF 렌더러 | spec 작성 전 | 추천값 수용(2026-10-16 "PDF는 기존 경로 재사용"이었으나 기존 경로는 PDF *읽기*라 생성기가 없음): ReportLab + 이미지에 이미 설치된 NanumGothic TrueType(독립 검사 결과 Noto CJK는 CFF라 ReportLab이 못 읽고 저장소에 폰트 바이너리가 없음). 사용자가 Noto Sans KR을 원하면 11MB 폰트 vendoring 승인이 필요하다 |
| 일일 상한 | spec 작성 전 | 추천값: 초안 3건/일(`tunable`, 승인 행 cap) |
