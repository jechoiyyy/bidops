# 미해결 문제 색인

2026-10-21 문서 정리. 중복 RL 판정 문제는 합쳤고 명시적으로 해결된 항목은 현재 문제 목록에서 제외했다. 나머지는 원래 관측일·재현·영향·잔여 한계를 유지했다. **오래됐다는 이유로 해결 처리하지 않았으며 이번 작업에서 제품·운영·모델을 재검증하지 않았다.**

## 현재 우선 확인

- 2026-11-17 통합 개발 Compose의 초기 기동 지연·worker 경고는 [진단 기록](findings/operations.md#2026-11-17-통합-개발-compose의-응답-대기와-worker-경고)에 남긴다. 입력 손실 수정 뒤 최종 Compose E2E는 통과했으며, 초기 운영성 관측과 구분한다.

- RL-05 인수 reject: 10건 completed, 판정 일치 3/10·차단 조건 recall 0/7. 카드 일치 84/100이어도 447개 전부 unknown이다. [회사 대조 공백](findings/model-review.md), [실제 평가](../validation-runs/2026-10-19-rl/RL-05/README.md).
- RL-04 실제 초안 partial(4/6절): 실적·운영 절의 식별자 참조 검증 실패는 [실행 기록](../validation-runs/2026-10-17-rl/RL-04/README.md)을 따른다.
- 첨부 worker 자동 준비의 transaction·정책 경로 문제와 Mac 변환 제한은 아래 운영·문서 기록의 10월 항목을 먼저 확인한다.
- 문서 준비 UI는 구현됐지만 실패 재시작 UI, 입찰 delta 계산 worker, 인증/SSO는 [현황](status.md)의 미구현 범위다.

## 분야별 재현 기록

### 모델 판정·근거 대조

- [9월 심층검토 v2 조치와 잔여 품질 범위](findings/model-review.md#2026-09-22-심층검토-고도화의-처리-범위)
- [RL-03 결정적 대조가 요구사항을 회사 사실에 연결하지 못해 gap을 하나도 찾지 못한다 (2026-10-20, 미해결)](findings/model-review.md#rl-03-결정적-대조가-요구사항을-회사-사실에-연결하지-못해-gap을-하나도-찾지-못한다-2026-10-20-미해결)
- [RL-03 카드 판정은 제약 하나의 검증 실패로 판정 전체가 사람 검토로 끝난다 (2026-10-18, 설계·구현됨, 실제 증명 대기)](findings/model-review.md#rl-03-카드-판정은-제약-하나의-검증-실패로-판정-전체가-사람-검토로-끝난다-2026-10-18-설계구현됨-실제-증명-대기)
- [실제 Qwen 회사 대조가 근거 ID와 주장 ID를 혼용한다 (2026-09-22, 미해결)](findings/model-review.md#실제-qwen-회사-대조가-근거-id와-주장-id를-혼용한다-2026-09-22-미해결)
- [심층 보고서의 빈 결과·서버 설명에도 무관한 claim 연결이 필요해진다 (2026-09-22, 미해결)](findings/model-review.md#심층-보고서의-빈-결과서버-설명에도-무관한-claim-연결이-필요해진다-2026-09-22-미해결)
- [심층 재실행 상태가 이전 완료 보고서 조회를 막고 문서 기준 차이를 설명하지 않는다 (2026-09-22, 미해결)](findings/model-review.md#심층-재실행-상태가-이전-완료-보고서-조회를-막고-문서-기준-차이를-설명하지-않는다-2026-09-22-미해결)
- [심층 화면의 수정본 표시와 초안 갱신이 현재 보고서에 정확히 결합되지 않는다 (2026-09-22, 미해결)](findings/model-review.md#심층-화면의-수정본-표시와-초안-갱신이-현재-보고서에-정확히-결합되지-않는다-2026-09-22-미해결)
- [심층 종합 조각 간 근거 중복 제거가 뒤 호출의 근거를 없앤다 (2026-09-22, 미해결)](findings/model-review.md#심층-종합-조각-간-근거-중복-제거가-뒤-호출의-근거를-없앤다-2026-09-22-미해결)
- [심층 보고서가 사업 위험과 근거 검증 실패를 같은 것으로 요약한다 (2026-09-22, 미해결)](findings/model-review.md#심층-보고서가-사업-위험과-근거-검증-실패를-같은-것으로-요약한다-2026-09-22-미해결)
- [심층 보고서의 절별 조립이 무관한 결과를 채우고 일부 본문을 생략한다 (2026-09-22, 미해결)](findings/model-review.md#심층-보고서의-절별-조립이-무관한-결과를-채우고-일부-본문을-생략한다-2026-09-22-미해결)
- [심층 회사 적합성 입력이 문서 조각과 프로필 조각을 순번으로만 짝짓는다 (2026-09-22, 미해결)](findings/model-review.md#심층-회사-적합성-입력이-문서-조각과-프로필-조각을-순번으로만-짝짓는다-2026-09-22-미해결)
- [심층 검증 요약 건수가 실제 검사 목록과 다른 기준으로 계산된다 (2026-09-22, 미해결)](findings/model-review.md#심층-검증-요약-건수가-실제-검사-목록과-다른-기준으로-계산된다-2026-09-22-미해결)
- [C-2 stage 2 구현이 측정된 방법과 어긋나 있었다](findings/model-review.md#c-2-stage-2-구현이-측정된-방법과-어긋나-있었다)
- [발주계획 Qwen 잘림 응답의 실패 token 계측이 보존되지 않는다](findings/model-review.md#발주계획-qwen-잘림-응답의-실패-token-계측이-보존되지-않는다)
- [현재 보고서 renderer가 screening v3를 처리하지 못한다](findings/model-review.md#현재-보고서-renderer가-screening-v3를-처리하지-못한다)
- [실제 심층 검토 품질 corpus와 사람 gold가 부족하다](findings/model-review.md#실제-심층-검토-품질-corpus와-사람-gold가-부족하다)
- [C-1과 C-2가 모델 호출 경계를 서로 반대로 잡는다](findings/model-review.md#c-1과-c-2가-모델-호출-경계를-서로-반대로-잡는다)
- [C-1 모델명이 바뀌어 기존 실행·판정 row가 새 실행에서 거부된다](findings/model-review.md#c-1-모델명이-바뀌어-기존-실행판정-row가-새-실행에서-거부된다)
- [`policy_quality` snapshot 모양이 바뀌어 이전에 만든 미실행 심층 검토가 503으로 닫힌다](findings/model-review.md#policy_quality-snapshot-모양이-바뀌어-이전에-만든-미실행-심층-검토가-503으로-닫힌다)
- [개요 attempt와 암호화된 원응답 사이에 직접 FK가 없다](findings/model-review.md#개요-attempt와-암호화된-원응답-사이에-직접-fk가-없다)
- [요구사항 대조 검사가 ID 체계를 가진 실제 문서에서 구조적으로 실패한다](findings/model-review.md#요구사항-대조-검사가-id-체계를-가진-실제-문서에서-구조적으로-실패한다)
- [mock 종단의 개요 검토가 실제 참조 실행과 응답에서 구분되지 않는다](findings/model-review.md#mock-종단의-개요-검토가-실제-참조-실행과-응답에서-구분되지-않는다)
- [회사 프로필 원문 일부가 심층 모델 fact 입력에서 빠진다](findings/model-review.md#회사-프로필-원문-일부가-심층-모델-fact-입력에서-빠진다)
- [개요의 조건부 권고가 확인 기한을 생성하고 위치 검증이 주장 의미를 보장하지 않는다](findings/model-review.md#개요의-조건부-권고가-확인-기한을-생성하고-위치-검증이-주장-의미를-보장하지-않는다)
- [2026-09-03~09-07 실제 참조 실행의 개요 검증 실패](findings/model-review.md#2026-09-0309-07-실제-참조-실행의-개요-검증-실패)
- [lifecycle projection의 Protocol 요구 메서드와 구현 불일치](findings/model-review.md#lifecycle-projection의-protocol-요구-메서드와-구현-불일치)
- [Qwen v5 실표본4건이 모두 결정적 검사에서 종료된다 (2026-09-11, 미완료)](findings/model-review.md#qwen-v5-실표본4건이-모두-결정적-검사에서-종료된다-2026-09-11-미완료)
- [개요 worker의 claim 루프가 재시도 상한을 무시한다 (2026-09-16, 코드 수정 진행 중)](findings/model-review.md#개요-worker의-claim-루프가-재시도-상한을-무시한다-2026-09-16-코드-수정-진행-중)
- [회사 핏은 심층 검토를 막는데 품질을 잴 장치가 없다 (2026-09-18, 미해결)](findings/model-review.md#회사-핏은-심층-검토를-막는데-품질을-잴-장치가-없다-2026-09-18-미해결)
- [사전규격 개요는 운영 중인데 표본 점검 라벨을 담을 자리가 없다 (2026-09-18, 미해결)](findings/model-review.md#사전규격-개요는-운영-중인데-표본-점검-라벨을-담을-자리가-없다-2026-09-18-미해결)
- [개요 완료→심층검토의 실행 상태와 실무자 동선 불일치 (2026-09-22, 미해결)](findings/model-review.md#개요-완료심층검토의-실행-상태와-실무자-동선-불일치-2026-09-22-미해결)

### 첨부·변환·문서 준비

- [0910 신규 RFP 절 후보 검사 실패 (2026-09-11 운영 core 재준비6건 해결) — 잔여 확인](findings/documents.md#0910-신규-rfp-절-후보-검사-실패-2026-09-11-운영-core-재준비6건-해결)
- [R5 런타임 이미지에 `fc-list`가 없어 native 변환이 전부 실패했다 (2026-09-10, 해결) — 잔여 확인](findings/documents.md#r5-런타임-이미지에-fc-list가-없어-native-변환이-전부-실패했다-2026-09-10-해결)
- [HP 평가 후보116 HWP의 native 검증 실패 (2026-10-15, 미해결)](findings/documents.md#hp-평가-후보116-hwp의-native-검증-실패-2026-10-15-미해결)
- [Rosetta 변환 실패로 `차단`된 사전규격 첨부를 다시 취득할 경로가 없다 (2026-10-15, 미해결)](findings/documents.md#rosetta-변환-실패로-차단된-사전규격-첨부를-다시-취득할-경로가-없다-2026-10-15-미해결)
- [요구사항 표의 행별 셀 위치 차이로 심층검토가 호출 전에 실패한다 (2026-09-22, 미해결)](findings/documents.md#요구사항-표의-행별-셀-위치-차이로-심층검토가-호출-전에-실패한다-2026-09-22-미해결)
- [판정 입력에 참여 판단용 날짜·비율 항목이 없고 늘리려면 검증기 여섯 곳을 함께 열어야 한다 (2026-09-21, 미해결)](findings/documents.md#판정-입력에-참여-판단용-날짜비율-항목이-없고-늘리려면-검증기-여섯-곳을-함께-열어야-한다-2026-09-21-미해결)
- [host 측정이 정상 PDF를 손상 문서로 판정한다](findings/documents.md#host-측정이-정상-pdf를-손상-문서로-판정한다)
- [legacy 첨부 취득이 객체 식별자를 provenance 자리에 넣어 운영 백엔드에서 원문을 잃는다](findings/documents.md#legacy-첨부-취득이-객체-식별자를-provenance-자리에-넣어-운영-백엔드에서-원문을-잃는다)
- [문서 준비와 실패 심층 검토 재시작을 화면에서 완료할 수 없다](findings/documents.md#문서-준비와-실패-심층-검토-재시작을-화면에서-완료할-수-없다)
- [이 변경 전에 만들어진 문서 구조에는 segment manifest가 없다](findings/documents.md#이-변경-전에-만들어진-문서-구조에는-segment-manifest가-없다)
- [개요 제목 인식이 공백·번호·표 구조를 놓치고 목차를 본문으로 선택한다](findings/documents.md#개요-제목-인식이-공백번호표-구조를-놓치고-목차를-본문으로-선택한다)
- [HWP/HWPX 구조의 page 값은 실제 PDF 페이지가 아니다](findings/documents.md#hwphwpx-구조의-page-값은-실제-pdf-페이지가-아니다)
- [[해결됨] 필수 RFP의 rhwp SVG PDF가 표 안의 원문을 보존하지 못한다 (2026-09-08)](findings/documents.md#해결됨-필수-rfp의-rhwp-svg-pdf가-표-안의-원문을-보존하지-못한다-2026-09-08)
- [[원인 확인] notice 142 표준 PDF 준비가 300초 deadline에서 종료됨 (2026-09-09)](findings/documents.md#원인-확인-notice-142-표준-pdf-준비가-300초-deadline에서-종료됨-2026-09-09)
- [pdf_preparation_failed가 변환기의 실제 오류 코드를 감춘다 (2026-09-10)](findings/documents.md#pdf_preparation_failed가-변환기의-실제-오류-코드를-감춘다-2026-09-10)
- [같은 문서 버전의 native 구조가 기존 구조와 다르면 준비를 거부한다 (2026-09-10)](findings/documents.md#같은-문서-버전의-native-구조가-기존-구조와-다르면-준비를-거부한다-2026-09-10)
- [개요 범위 보조 호출에 temperature 0을 줄 수 없다 (2026-09-10)](findings/documents.md#개요-범위-보조-호출에-temperature-0을-줄-수-없다-2026-09-10)
- [실표본에서 사람 확정 흐름을 재현할 문서가 없다 (2026-09-10)](findings/documents.md#실표본에서-사람-확정-흐름을-재현할-문서가-없다-2026-09-10)
- [0910의 수동 범위·대체 문서·안전 오류 후속 (2026-09-11, 미완료)](findings/documents.md#0910의-수동-범위대체-문서안전-오류-후속-2026-09-11-미완료)
- [운영 `attachment.name`이 나라장터 자리표시자라 파일명 대조가 무의미하다 (2026-09-11, 경고로 완화됨·미해결)](findings/documents.md#운영-attachmentname이-나라장터-자리표시자라-파일명-대조가-무의미하다-2026-09-11-경고로-완화됨미해결)
- [2026-10-09 로컬 ARM Mac의 Rosetta 문서 변환 실패](findings/documents.md#2026-10-09-로컬-arm-mac의-rosetta-문서-변환-실패)
- [2026-10-14 HP 카드 쪽 연결의 실측 한계와 PDF 표 겹침](findings/documents.md#2026-10-14-hp-카드-쪽-연결의-실측-한계와-pdf-표-겹침)

### 운영·데이터·보안

- [백업 실행이 DB 컨테이너를 다시 만들고, DB가 끊기면 web의 선별 큐 스레드가 죽은 채 남는다 (2026-11-21, 미해결)](findings/operations.md#백업-실행이-db-컨테이너를-다시-만들고-db가-끊기면-web의-선별-큐-스레드가-죽은-채-남는다-2026-11-21-미해결)

- [공고 날의 수집은 끝났는데 적재가 실패하면 그날이 조용히 빠졌다 (2026-11-18 독립 검증 B2, 코드 수정·운영 반영)](findings/operations.md#공고-날의-수집은-끝났는데-적재가-실패하면-그날이-조용히-빠졌다-2026-11-18-독립-검증-b2-코드-수정운영-반영)
- [누락일 감지 창보다 오래된 날은 다시 보이지 않는다 (2026-11-18 독립 검증 B1, 수용 제약·완화)](findings/operations.md#누락일-감지-창보다-오래된-날은-다시-보이지-않는다-2026-11-18-독립-검증-b1-수용-제약완화)
- [폴링 GET 한 번의 timeout이 따라잡기 범위 전체를 멈췄다 (2026-11-18, 코드 수정·운영 반영)](findings/operations.md#폴링-get-한-번의-timeout이-따라잡기-범위-전체를-멈췄다-2026-11-18-코드-수정운영-반영)
- [운영 상태 서비스가 host 재시작 뒤 올라오지 않는다 (2026-11-18, 코드 수정·운영 반영)](findings/operations.md#운영-상태-서비스가-host-재시작-뒤-올라오지-않는다-2026-11-18-코드-수정운영-반영)
- [prod `make build`가 bootstrap 대상을 arm64로 빌드해 실패한다 (2026-11-18, 미해결)](findings/operations.md#prod-make-build가-bootstrap-대상을-arm64로-빌드해-실패한다-2026-11-18-미해결)
- [첨부 취득 종결에서 부르는 자동 문서 준비가 커밋되지 않는다 (2026-10-15, 커밋 해소·정책 경로 브랜치 수정)](findings/operations.md#첨부-취득-종결에서-부르는-자동-문서-준비가-커밋되지-않는다-2026-10-15-커밋-해소정책-경로-브랜치-수정)
- [WSL2 종료로 C-2 v4 승인 프롬프트와 운영 DB가 사라졌다 (2026-10-14, 일부 해소)](findings/operations.md#wsl2-종료로-c-2-v4-승인-프롬프트와-운영-db가-사라졌다-2026-10-14-일부-해소)
- [이전 백업에서 확인한 과거 회사 프로필 객체 버전 누락 (2026-09-29, 미해결)](findings/operations.md#이전-백업에서-확인한-과거-회사-프로필-객체-버전-누락-2026-09-29-미해결)
- [일일 발주계획 트랙이 C-2 단계에서 매일 409로 죽었다 (B-1)](findings/operations.md#일일-발주계획-트랙이-c-2-단계에서-매일-409로-죽었다-b-1)
- [발주계획 회차에 `info` 등급 경고 하나만 있어도 C-2가 영구히 막힌다 (W-2)](findings/operations.md#발주계획-회차에-info-등급-경고-하나만-있어도-c-2가-영구히-막힌다-w-2)
- [수집 실패일·중단일은 자동으로 따라잡지 않는다 (W-3·W-4)](findings/operations.md#수집-실패일중단일은-자동으로-따라잡지-않는다-w-3w-4)
- [워커가 죽으면 `대기` 실행이 닫히지 않고 남는다 (W-5, 제품 쪽)](findings/operations.md#워커가-죽으면-대기-실행이-닫히지-않고-남는다-w-5-제품-쪽)
- [model_digest를 바꾸면 generation config도 함께 새로 발행해야 한다](findings/operations.md#model_digest를-바꾸면-generation-config도-함께-새로-발행해야-한다)
- [승인 사설 vLLM이 weight revision을 노출하지 않는다](findings/operations.md#승인-사설-vllm이-weight-revision을-노출하지-않는다)
- [감독 작업 transcript에 G2B API key가 노출됐다](findings/operations.md#감독-작업-transcript에-g2b-api-key가-노출됐다)
- [ADR-0027의 21일 재조회 근거가 종단 관측에서 재현되지 않는다](findings/operations.md#adr-0027의-21일-재조회-근거가-종단-관측에서-재현되지-않는다)
- [PostgreSQL 전용 테스트가 스키마 변경 뒤에도 갱신되지 않고 skip됐다](findings/operations.md#postgresql-전용-테스트가-스키마-변경-뒤에도-갱신되지-않고-skip됐다)
- [애플리케이션 스택의 publish port가 host에서 열리지 않는다](findings/operations.md#애플리케이션-스택의-publish-port가-host에서-열리지-않는다)
- [암호화된 model-response active object는 stored-byte hash로 검증할 수 없다](findings/operations.md#암호화된-model-response-active-object는-stored-byte-hash로-검증할-수-없다)
- [legacy mutation 일부가 담당자 이름과 감사 기록 없이 실행된다](findings/operations.md#legacy-mutation-일부가-담당자-이름과-감사-기록-없이-실행된다)
- [개발계정 일일 1,000회 한도의 실제 여유가 측정되지 않았다](findings/operations.md#개발계정-일일-1000회-한도의-실제-여유가-측정되지-않았다)
- [사설 vLLM model artifact가 불변 digest로 고정되지 않았다](findings/operations.md#사설-vllm-model-artifact가-불변-digest로-고정되지-않았다)
- [실제 backup·권한·복구 훈련이 없다](findings/operations.md#실제-backup권한복구-훈련이-없다)
- [운영 백엔드가 `experiments/`를 런타임 의존한다](findings/operations.md#운영-백엔드가-experiments를-런타임-의존한다)
- [`experiments/`의 회사자료가 gitignore되어 `git archive` 사본이 자족적이지 않다](findings/operations.md#experiments의-회사자료가-gitignore되어-git-archive-사본이-자족적이지-않다)
- [B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다](findings/operations.md#b-f-설계-승인-baseline과-manifest가-없어-전체-설계-게이트를-완료할-수-없다)
- [`ollama_unavailable` 실패 사유 문자열이 이름만 남았다](findings/operations.md#ollama_unavailable-실패-사유-문자열이-이름만-남았다)
- [실제 C-1 부분 결과의 게시 실패가 남아 있다](findings/operations.md#실제-c-1-부분-결과의-게시-실패가-남아-있다)
- [입찰 delta 조회가 runtime 테이블 권한 누락으로 실패한다](findings/operations.md#입찰-delta-조회가-runtime-테이블-권한-누락으로-실패한다)
- [v4 PDF snapshot/input bounded 단계 상태 (2026-09-08)](findings/operations.md#v4-pdf-snapshotinput-bounded-단계-상태-2026-09-08)
- [전체 backend·화면 스위트의 기존 실패 4건이 rhwp 단계와 무관하게 남아 있다 (2026-09-10)](findings/operations.md#전체-backend화면-스위트의-기존-실패-4건이-rhwp-단계와-무관하게-남아-있다-2026-09-10)
- [확정 대기 target에 검토 manifest 참조가 결속되지 않는다 (2026-09-10)](findings/operations.md#확정-대기-target에-검토-manifest-참조가-결속되지-않는다-2026-09-10)
- [승인된 Qwen 참조 worker의 목적지 제한 미확인 (2026-09-11, 추가 조회 생략 후 참조 실행)](findings/operations.md#승인된-qwen-참조-worker의-목적지-제한-미확인-2026-09-11-추가-조회-생략-후-참조-실행)
- [첨부 worker의 자동 문서 준비가 DB 권한에서 거부된다 (2026-09-15, 미해결)](findings/operations.md#첨부-worker의-자동-문서-준비가-db-권한에서-거부된다-2026-09-15-미해결)
- [운영 모델 주소가 TEST-NET 자리표시자로 배포됐다 (2026-09-16, 운영 조치 완료·코드 방지 진행 중)](findings/operations.md#운영-모델-주소가-test-net-자리표시자로-배포됐다-2026-09-16-운영-조치-완료코드-방지-진행-중)

### 화면·수집·회귀 검증

- [운영 DB의 C-2 policy v2가 활성화 API 없이 active·passed로 있다 (2026-09-18, 운영 조치 완료 2026-09-19) — 잔여 확인](findings/product.md#운영-db의-c-2-policy-v2가-활성화-api-없이-activepassed로-있다-2026-09-18-운영-조치-완료-2026-09-19)
- [팔레트 전환 뒤 화면 단위 시각 회귀를 잡을 기준선이 없다 (해결) — 잔여 확인](findings/product.md#팔레트-전환-뒤-화면-단위-시각-회귀를-잡을-기준선이-없다-해결)
- [기존 심층 검토 자동 시작 테스트 13건이 main에서 실패한다 (2026-11-19 확인, 미해결)](findings/product.md#기존-심층-검토-자동-시작-테스트-13건이-main에서-실패한다-2026-11-19-확인-미해결)
- [발주계획 목록 검색 테스트 6건이 PostgreSQL에서 실패한다 (2026-11-18, 미해결·원인 미확인)](findings/product.md#발주계획-목록-검색-테스트-6건이-postgresql에서-실패한다-2026-11-18-미해결원인-미확인)
- [데모 기준 `c50ed55`의 화면 스위트에 기존 실패 3종이 있다 (2026-10-12, 미해결)](findings/product.md#데모-기준-c50ed55의-화면-스위트에-기존-실패-3종이-있다-2026-10-12-미해결)
- [심층 보고서 직접 진입 시 공통 상세 레이아웃 CSS가 로드되지 않는다 (2026-09-22, 미해결)](findings/product.md#심층-보고서-직접-진입-시-공통-상세-레이아웃-css가-로드되지-않는다-2026-09-22-미해결)
- [`test_auto_deep_review_start.py` 11건이 `bda1288` 이후 실패한다 (2026-09-22, 미해결)](findings/product.md#test_auto_deep_review_startpy-11건이-bda1288-이후-실패한다-2026-09-22-미해결)
- [심층 검토 화면에 8자 축약 식별자 두 곳이 남아 있다 (2026-09-21, 미해결)](findings/product.md#심층-검토-화면에-8자-축약-식별자-두-곳이-남아-있다-2026-09-21-미해결)
- [프런트 fixture의 심층 검토 오류 코드가 백엔드 계약에 없는 값이다 (2026-09-21, 미해결)](findings/product.md#프런트-fixture의-심층-검토-오류-코드가-백엔드-계약에-없는-값이다-2026-09-21-미해결)
- [`test_order_plan_list_v2.py` 6건이 clean main에서 실패한다 (2026-09-21, 미해결)](findings/product.md#test_order_plan_list_v2py-6건이-clean-main에서-실패한다-2026-09-21-미해결)
- [발주 예정월·사전규격 등록 후 경과를 알리는 재확인 신호가 없다 (2026-09-21, 미해결)](findings/product.md#발주-예정월사전규격-등록-후-경과를-알리는-재확인-신호가-없다-2026-09-21-미해결)
- [발주처 담당자 연락처가 정규화 스키마 밖에 남아 있다 (2026-09-21, 결정 보류)](findings/product.md#발주처-담당자-연락처가-정규화-스키마-밖에-남아-있다-2026-09-21-결정-보류)
- [입찰공고 `budget`이 세 원문 필드의 fallback이라 무엇을 본 값인지 알 수 없다 (2026-09-21, 미해결)](findings/product.md#입찰공고-budget이-세-원문-필드의-fallback이라-무엇을-본-값인지-알-수-없다-2026-09-21-미해결)
- [발주계획 일괄 추적 시작에는 record backfill도 선택 상한도 없다 (2026-09-20, 미해결)](findings/product.md#발주계획-일괄-추적-시작에는-record-backfill도-선택-상한도-없다-2026-09-20-미해결)
- [담당자 이름은 신원을 증명하지 않는다](findings/product.md#담당자-이름은-신원을-증명하지-않는다)
- [심층 검토 보고서를 사업기회·공고로 되찾을 목록 계약이 없다](findings/product.md#심층-검토-보고서를-사업기회공고로-되찾을-목록-계약이-없다)
- [Go/No-Go 결정 대기 사업기회를 N+1 없이 집계할 endpoint가 없다](findings/product.md#gono-go-결정-대기-사업기회를-n1-없이-집계할-endpoint가-없다)
- [발주계획 목록 API에 "사람 피드백 미기록" 필터가 없다](findings/product.md#발주계획-목록-api에-사람-피드백-미기록-필터가-없다)
- [사전규격 목록 API에 마감 구간 필터도 임박 집계도 없다](findings/product.md#사전규격-목록-api에-마감-구간-필터도-임박-집계도-없다)
- [발주계획 추적 결정(결정 1)을 저장할 REST 계약이 없다](findings/product.md#발주계획-추적-결정결정-1을-저장할-rest-계약이-없다)
- [보고서의 문서 inventory 패널이 문서 하나만 보여 준다](findings/product.md#보고서의-문서-inventory-패널이-문서-하나만-보여-준다)
- [사전규격 목록의 등급 필터가 브라우저 쪽이라 집계와 비대칭이다](findings/product.md#사전규격-목록의-등급-필터가-브라우저-쪽이라-집계와-비대칭이다)
- [리뷰 저장 hook과 첨부 취득 worker가 같은 문서 집합으로 묶음을 둘 만들 수 있다](findings/product.md#리뷰-저장-hook과-첨부-취득-worker가-같은-문서-집합으로-묶음을-둘-만들-수-있다)
- [PDF 개요 연결 검증에서 확인한 범위 밖 회귀 실패 (2026-09-07)](findings/product.md#pdf-개요-연결-검증에서-확인한-범위-밖-회귀-실패-2026-09-07)
- [화면 스위트의 발주계획·공통 골격 spec 53건이 main에서 실패한다 (2026-09-16, 원인 미확인)](findings/product.md#화면-스위트의-발주계획공통-골격-spec-53건이-main에서-실패한다-2026-09-16-원인-미확인)
- [발주계획 화면이 누적 목록을 500행씩 전부 받아 브라우저에서 거른다 (2026-09-18, 미해결)](findings/product.md#발주계획-화면이-누적-목록을-500행씩-전부-받아-브라우저에서-거른다-2026-09-18-미해결)
- [2026-10-17 브리핑 지역 제외에 쓸 참가 가능 지역 값이 수집되지 않음](findings/product.md#2026-10-17-브리핑-지역-제외에-쓸-참가-가능-지역-값이-수집되지-않음)

### 수용한 제약

- [목록 행 체크박스의 클릭 대상이 24px에 못 미친다 (2026-09-20, 수용됨)](findings/accepted.md#목록-행-체크박스의-클릭-대상이-24px에-못-미친다-2026-09-20-수용됨)
- [승인된 프로필 기준선 commit이 현재 저장소 history에 없다 (2026-08-31 결정으로 수용)](findings/accepted.md#승인된-프로필-기준선-commit이-현재-저장소-history에-없다-2026-08-31-결정으로-수용)
- [사업기회 추적 이력을 읽을 계약이 없고 구역별 집계도 서버가 세지 않는다](findings/accepted.md#사업기회-추적-이력을-읽을-계약이-없고-구역별-집계도-서버가-세지-않는다)
- [비교 근거 최종 결정 경로가 runtime `app` 역할에서 실행되지 않는다 (2026-09-17, 수용됨)](findings/accepted.md#비교-근거-최종-결정-경로가-runtime-app-역할에서-실행되지-않는다-2026-09-17-수용됨)
- [C-1 수동 경로가 후보 policy를 받고 그 `제외`가 기본 목록에서 숨는다 (2026-09-18, 수용됨)](findings/accepted.md#c-1-수동-경로가-후보-policy를-받고-그-제외가-기본-목록에서-숨는다-2026-09-18-수용됨)
- [1280 폭 대시보드에 세로 스크롤이 생긴다 (2026-09-19, 수용됨)](findings/accepted.md#1280-폭-대시보드에-세로-스크롤이-생긴다-2026-09-19-수용됨)

## 해결 기록

해결이 명시되고 별도 잔여 과제가 없는 32개 항목은 목록에서 제외했다. 예를 들어 RL 큰 영역 입력 거부는 selector v4·정책 v10/v11로 해소됐다. 블록 하나가 한도를 넘으면 여전히 거부하며, 대조 품질은 여전히 인수 실패다. 해결 기록의 제거가 운영 재검증을 뜻하지 않는다.

과거 재현·수정 결과는 `git show b5a61e4:docs/tracking/findings.md`, 반복 방지 규칙은 [engineering-notes](../engineering-notes.md), 실행 증거는 [validation-runs](../validation-runs/)에서 찾는다. 부분 해소·코드 수정 후 운영 미검증·키 회전 미확인·사용자 수용 항목은 위 상세에 남겼다. 새 문제는 해당 분야에 재현 조건·영향·미해결 이유·후속 방향을 기록하고 이 색인에 연결한다.
