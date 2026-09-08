# Qwen 사전규격 개요 검토 — PDF 페이지 근거

모델: `qwen3.8:27b` · 프롬프트: `prespec-overview-page-review-reference-v4` · `quality_status=unmeasured_reference`

글자수·줄수 제한 없이 Qwen이 실제 생성한 결과다. 사실 설명과 모델 검토 의견을 구분했다. 아래 PDF 페이지는 표지를 포함해 세는 변환 PDF의 실제 순번이며, 문서에 인쇄된 쪽수와 다를 수 있다. 원문 HWP/HWPX와 변환 PDF의 해시는 실행 manifest에 결속했다.

원응답은 암호화 저장하고 기존 DB 개요 리뷰는 변경하지 않았다. 근거 검사 통과는 운영 품질 승인이나 최종 참여 판단을 의미하지 않는다. 아래 설명은 모델 출력이며 잘못된 내용이 확인되면 별도 검토 기록으로 표시하고 원응답을 고치지 않는다.

## RCMS 연계모듈 전환 및 통합 Ezbaro 연계모듈 구축

내부 ID: 614 · 실행 상태: `validation_failed`

[근거 PDF 열기](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf) · 검토 페이지: 3, 4, 5, 6

**검증 실패 — 아래는 담당자 확인용 원출력이며 완료 결과가 아님.** 사유: fact_number_not_on_cited_pages, latin_term_not_on_cited_pages

### 사업 개요

부처 연구비 관리 시스템의 연계 방식이 통합 개편되고 기존 RCMS 연계 모듈이 2026년 12월 31일부로 종료될 예정이므로, 진흥원은 연구비 집행·정산 업무의 연속성을 확보하기 위해 RCMS 연계모듈을 전환하고 통합Ezbaro 연계모듈을 신규 구축하는 소프트웨어 개발 용역을 발주한다. (PDF 3페이지) [PDF 3페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=3)

### 주요 과업

기존 RCMS 연계 환경을 분석·설계하고, 연계 모듈을 재구축하여 신규 통합 연계모듈로 전환하며, 데이터 이관과 전송·오류 관리 기능을 개선한다. (PDF 4페이지 · PDF 6페이지) [PDF 4페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=4) · [PDF 6페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=6)

통합Ezbaro 연계모듈을 설치·구축하여 과제·예산·연구비 집행정보 연계 기능을 개발하고, 내부 정보시스템과 비목·과제 매핑 체계를 구축한다. (PDF 4페이지 · PDF 6페이지) [PDF 4페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=4) · [PDF 6페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=6)

두 시스템 연계의 단위·통합 시험과 상호연동 시험을 수행하고, 연계 오류 모니터링·재처리 체계를 구축하여 운영환경에 반영한다. (PDF 4페이지 · PDF 5페이지 · PDF 6페이지) [PDF 4페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=4) · [PDF 5페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=5) · [PDF 6페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=6)

### 사업 규모와 일정

사업금액은 153,000,000원(VAT 포함)이며, 사업기간은 계약체결일로부터 6개월이다. (PDF 3페이지) [PDF 3페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=3)

RCMS 연계모듈 전환은 기존 서비스 일몰일인 2026년 12월 31일 이전에 완료해야 하며, 통합Ezbaro 연계모듈 구축은 순차적으로 추진된다. (PDF 3페이지 · PDF 5페이지) [PDF 3페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=3) · [PDF 5페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=5)

### 핵심 조건

연계 범위는 RCMS 및 통합Ezbaro 운영기관이 배포·공지하는 연계 규격(전문, API 등)에 정의된 범위를 기준으로 한다. (PDF 4페이지) [PDF 4페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=4)

RCMS 및 통합Ezbaro 운영기관의 연계모듈 배포·개통 일정에 따라 추진 일정이 조정될 수 있다. (PDF 6페이지) [PDF 6페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=6)

### 검토 포인트 — Qwen 판단

- 본 사업은 기존 시스템에서 신규 통합 모듈로의 전환과 신규 연계모듈 구축이 동시에 요구되는 개발 용역으로, 연계 규격에 대한 이해와 데이터 정합성 검증 역량이 핵심이다. 기존 RCMS 연계 환경 분석과 신규 모듈 구축 간 업무 공백을 방지하는 전환 계획과, 운영기관 연계 규격에 대한 대응 능력이 수행 적합성을 판단하는 우선 확인 쟁점이다.

### 추가 확인 사항

- 세부 추진 일정은 착수 후 발주기관과 협의하여 확정되며, RCMS 및 통합Ezbaro 운영기관의 연계모듈 배포·개통 일정에 따라 조정될 수 있다. (PDF 6페이지)
- 회사 역량·참여 요건 대조는 아직 이루어지지 않았다.

### 입력·검토 한계

- 본 요약은 제공된 PDF 3~6페이지의 개요 및 추진체계 본문을 대상으로 하며, 전체 문서의 세부 요구사항이나 제안요청 내용을 검토하지 않았다. (PDF 3~6페이지)

### 근거 PDF 페이지

- [PDF 3페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=3)
- [PDF 4페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=4)
- [PDF 5페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=5)
- [PDF 6페이지](/home/jechoi/projects/bidops/.dryforge/pipeline-20260903-20260907/overview-pdf-v4-614-single/614.pdf#page=6)

## 변환 및 검증 범위

PDF는 저장소의 rhwp SVG 렌더와 Chromium 인쇄로 만든 참조 변환본이다. 한컴 원본과 동일한 페이지 배치를 보증하지 않는다. 인용 페이지는 함께 제공하는 PDF에서 확인해야 한다. 현재 운영 HWP/HWPX 구조의 page 필드(구역 순번)와 이번 pdf_page 필드(변환 PDF 실제 페이지)는 서로 대체하지 않는다.

자동 검사는 스키마, 선택한 PDF 페이지 범위, 사실 문장의 숫자·영문 명칭이 표시한 원문 페이지에 있는지, 사업금액을 계약금액으로 잘못 표현했는지를 확인했다. 인용문은 모델이 재생성하지 않으며 근거 PDF를 직접 조회한다. 의미상 정확성·필수 내용의 완전성·회사 적합성은 이 검사만으로 보증하지 않는다.
