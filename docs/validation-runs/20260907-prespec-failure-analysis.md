# 사전규격 미완료 원인 분석 — 2026-09-07

## 확인 범위

PostgreSQL 읽기 전용 조회에서 64건: completed 12, failed 9, needs_human_review 42, awaiting_document 1. 첨부 98개: 완료 90, 차단 8. 공고 건수와 첨부 개수는 합산하지 않는다. 추가 모델 호출·재파싱·DB 상태 변경은 하지 않았다.

DB snapshot의 source_sha256과 일치하는 보관 구조 JSON을 대조했다. 실패 응답 2건은 암호화 객체의 version과 평문 hash를 확인하고 메모리에서 검증했다. 원문·프롬프트·모델 응답 전문은 이 보고서에 포함하지 않는다.

## 원인

- 제목 경계 29건: no_end_heading 15, no_topic_heading 14. 파싱 실패를 의미하지 않는다.
- _normalise_heading_text는 내부 공백을 하나로만 줄인다. 허용 어휘 사업개요와 실제 사업 개요가 불일치한다. 마침표 없는 로마숫자 접두사도 남는다. 과업개요·감리개요·추진배경 및 필요성·제안요청내용 등은 9개 어휘 밖이다. paragraph 대체 인식은 표 셀을 읽지 않고 계층을 모두 1로 취급한다.
- no_end_heading은 올바른 시작을 찾았다는 뜻도 아니다. 공고 8은 4,392블록 중 ordinal 3,644에서 시작을 잡았다.
- PDF 경고 1건(59): pdf_poppler_fallback, pdf_stdlib_text_fallback. 현재 warnings가 하나라도 있으면 중단한다. 손상·OCR 필요가 확정된 것은 아니다.
- 파일 선택 12건: 동순위 후보 5, 파일명 어휘 미인식 3, ZIP 차단 뒤 사전공개문만 준비된 2, 제안요청서 PDF timeout 뒤 다른 첨부만 준비된 2.
- 원문 준비 대기 1건(70): 유일 첨부 ZIP 미지원. ZIP 내부 파일은 이번 조사에서 열지 않았으므로 내용 존재 여부를 단정하지 않는다.
- prompt_rejected 7건: 최종 JSON 프롬프트 24,000자 제한. Qwen 컨텍스트 한계나 모델 서버 오류가 아니다. 본문 범위 과대 선택과 블록 위치 정보 비용이 함께 작용한다. 74는 본문 1,984자, 340블록(빈 블록 263개), 프롬프트 25,899자다.
- validation_failed 1건(16): 조건부 추진 검토인데 conditions가 빈 배열. verification_due_at은 존재한다. JSON 구문 오류가 아닌 필드 간 규칙 위반이다.
- evidence_out_of_scope 1건(66): 범위 [56,205) 안이지만 paragraph-1-38/ordinal 68 및 paragraph-1-42/ordinal 72의 블록 키와 순번 조합이 snapshot과 불일치한다. 단순 범위 밖 인용으로만 설명하면 부정확하다.

## 완료 결과도 재검토 필요

공고 52의 실제 입력은 목차 10블록이었다. 목차 인식은 지정 어휘의 연속 구간만 인정하고, 중간 비대상 제목·빈 문단 등을 만나면 끝나므로 남은 목차가 본문 후보로 취급될 수 있다. 현재 completed는 출력 형식·위치 검증 결과이며 사실 정확성이나 본문 선택 품질을 보증하지 않는다. 나머지 완료 11건의 의미 품질 판정은 아직 완료하지 않았다.

## 처리 순서

1. 제목 공백·번호 정규화, 표 안 제목, 목차/본문 구분, 절 계층을 함께 수정하고 기존 완료 입력도 재점검한다.
2. 제안요청서 역할 지정·중복 형식 선택과 파일명 후보 규칙을 정비한다.
3. PDF timeout 원인을 제한된 재현으로 좁히고, ZIP은 경로·압축해제 크기·검사 경계를 갖춘 처리 후 문서를 선택한다.
4. 올바른 개요 구간으로 다시 길이를 측정한 뒤 빈 블록·중복 표 표현을 정비하고 필요한 경우 근거 위치 보존 분할을 설계한다.
5. 모델 응답 실패는 기존 결과를 보존하고 새 입력/시도로 검증한다. conditions나 근거 순번을 자동으로 만들어 채우지 않는다.

## 미완료 52건 상세

| 공고 | 화면 ID | 상태 | 확인 원인 |
|---|---:|---|---|
| pre:R26BD00270285 | 6 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270255 | 8 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270010 | 10 | needs_human_review | 제안요청서·과업지시서 동순위 |
| pre:R26BD00270346 | 14 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269783 | 15 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269067 | 16 | failed | 조건부 권고의 conditions 빈 배열 |
| pre:R26BD00269256 | 19 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269678 | 20 | needs_human_review | ZIP 미지원, 사전공개문만 준비됨 |
| pre:R26BD00269276 | 26 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269120 | 39 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269025 | 41 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269061 | 42 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269071 | 43 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269152 | 44 | needs_human_review | PDF·HWP 제안요청서 동순위 |
| pre:R26BD00269255 | 45 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269266 | 46 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269271 | 47 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269360 | 48 | failed | 프롬프트 120,929자 > 24,000자 |
| pre:R26BD00269387 | 49 | needs_human_review | 제안요청서 PDF 처리 timeout |
| pre:R26BD00269413 | 50 | failed | 프롬프트 155,040자 > 24,000자 |
| pre:R26BD00269439 | 51 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269473 | 53 | failed | 프롬프트 26,949자 > 24,000자 |
| pre:R26BD00269477 | 54 | failed | 프롬프트 27,830자 > 24,000자 |
| pre:R26BD00269493 | 55 | needs_human_review | 제안요청서 PDF 처리 timeout |
| pre:R26BD00269500 | 56 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269546 | 57 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269653 | 59 | needs_human_review | PDF 대체 추출 경고 |
| pre:R26BD00269663 | 60 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00269692 | 61 | needs_human_review | ZIP 미지원, 사전공개문만 준비됨 |
| pre:R26BD00269697 | 62 | needs_human_review | 사전규격서 파일명 미인식 |
| pre:R26BD00269746 | 63 | needs_human_review | 제안요청서·과업지시서 동순위 |
| pre:R26BD00269792 | 64 | needs_human_review | 제안요청서·과업지시서 동순위 |
| pre:R26BD00269794 | 65 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269867 | 66 | failed | 근거 block_key와 ordinal 조합 불일치 |
| pre:R26BD00269900 | 67 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00269941 | 70 | awaiting_document | 유일 첨부 ZIP 미지원 |
| pre:R26BD00270020 | 71 | needs_human_review | 제안요청서·과업지시서 동순위 |
| pre:R26BD00270033 | 72 | failed | 프롬프트 315,367자 > 24,000자 |
| pre:R26BD00270049 | 73 | failed | 프롬프트 52,463자 > 24,000자 |
| pre:R26BD00270066 | 74 | failed | 프롬프트 25,899자 > 24,000자 |
| pre:R26BD00270099 | 76 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270107 | 77 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00270148 | 79 | needs_human_review | 용역과업개요 파일명 미인식 |
| pre:R26BD00270161 | 81 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270227 | 82 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270228 | 83 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270300 | 84 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00270319 | 85 | needs_human_review | 끝 제목 미인식 |
| pre:R26BD00270425 | 86 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00270459 | 88 | needs_human_review | 개요 제목 미인식 |
| pre:R26BD00270468 | 89 | needs_human_review | 제안요청 파일명 미인식 |
| pre:R26BD00270475 | 90 | needs_human_review | 개요 제목 미인식 |
