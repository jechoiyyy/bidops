# SW 대상 사전규격 실제 개요 실행

## 범위와 입력

사용자의 2026-09-07 요청으로 SW사업대상 Y 64건을 실제 첨부 취득부터 개요까지 실행했다.
C-1 판정 자체, 심층 검토, 사람의 추적 선택은 실행하지 않았다.
원본 `prespecs-20260831-20260902`는 보존하고 새 파생 회차를 적재했다.

- 회차: `prespecs-20260831-20260902-sw-y-overview-20260907--20260906T181718.227147Z`
- 첨부: 98개, 실제 worker의 PostgreSQL/MinIO 저장 완료 90개, 차단 8개
- 모델: 사용자 지정 사설 Ollama의 `qwen3.8:27b`
- 모델 digest: `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`
- 이전 로컬 파싱 증거와 실제 DB 저장 실행을 구분한다. mock으로 대체하지 않았다.

## 모델 호출 경계

유휴 기존 분석 worker를 멈추고 합성 `app.workers.analysis --once`를 동시성 1로 실행했다.
Ollama 전용 환경과 별도 개요 정책 파일을 사용하고 active profile/policy ID는 비웠다.
host의 Docker 사용자 체인은 WSL 관리 경로로 직접 조회했다. 실행 container의 egress 주소에
한정하여 모델 IP·port와 나라장터 첨부 목적지만 허용하는 규칙을 추가했다.
모델 허용 port 연결과 기존 다른 model port의 차단을 실제 확인했다.

모델 endpoint·비밀·원문·프롬프트는 이 문서에 기록하지 않는다. 실제 전송 입력 미리보기는
비공개 실행 디렉터리에 저장했다. 회사 프로필은 개요 모델에 전송하지 않았다.
매 completion 전에 served model, digest, 모델의 `top_k=20`을 확인했고, thinking은
Ollama 호환 API의 `reasoning_effort=none`으로 비활성화했다.

첫 공고는 `pre:R26BD00269447`이며 입력 10 blocks, prompt 1,938자였다.
이후 실제 DB 입력을 검사해 나머지 모델 대상 13건과 prompt 한도 초과 7건을 구분했다.
총 대상은 14개 공고다. 아래 조회 결함으로 첫 공고에 추가 시도가 생성되어 1회 더 실행했다.
따라서 고유 공고 수와 모델 응답 실행 수를 구별한다. 결과는 모두 품질 미측정 참조 결과다.

## 실행 중 드러나 수정한 결함

1. 첨부 worker의 실제 변환이 격리 worker를 거치지 않았다. scratch adapter를 기본값으로
   연결하고 Compose에 scratch volume과 structure 쓰기·전용 읽기 자격증명을 추가했다.
2. worker의 첨부·공고·문서 행 잠금과 current version 갱신 권한이 부족했다.
   `notice.id`, `attachment.extract_status`, `document_version.is_current`의 열별 UPDATE만
   추가했다. 별도 PostgreSQL에서 table-wide UPDATE와 원문 metadata 수정 권한이 없음을 검증했다.
3. 개요 분석 입력이 source 원문 재다운로드 권한을 요구했다. 원문 검증은 snapshot 생성 시
   수행하고 분석 worker는 frozen lineage·clean scan·structure hash/version만 다시 검증한다.
4. 불변 overview snapshot에 불필요한 `FOR UPDATE`가 있었다. 변경 가능한 review·attempt
   잠금을 유지하고 snapshot에는 쓰기 권한을 추가하지 않았다.
5. 웹에 structure 전용 읽기 설정이 없었고, 재확인 실패 시 이전 ready snapshot을 재사용하여
   완료 리뷰를 대기로 되돌릴 수 있었다. 설정을 보완하고, 결정이 다르면 기존 snapshot을
   보존하되 현재 입력에서 분리하여 `needs_human_review`와 안전한 감사 사유로 기록한다.
   같은 입력 hash의 snapshot 중복 생성은 DB 계약상 금지돼 있으므로 기존 row를 덮어쓰지 않는다.

저장 장애 진단 중 안전 오류 코드로 남은 시도도 보존했다. 모델의 출력 검증 실패는
자동 수정하거나 검증을 완화하지 않았다. 이 실행의 검증 통과는 출력 형식·근거 위치 검사이며
사람이 모든 사업 사실과 권고 품질을 확인했다는 뜻이 아니다.

## 회사 프로필

정본 원문을 덮어쓰지 않고 별도 구조화 후보를 만들었다. 기존 43 facts의 key·value·status가
모두 보존됨을 실제 importer로 대조했다. 원문에서 명시적으로 confirmed인 사업영역·인증
18개를 추출하고, null·대표 실적·고객·제품 등 56개를 unknown으로 구조화했다.

- 새 profile version: 2, ID `d1409ffb-c42e-4e81-b9d3-d5097ca66e02`
- digest: `838c3505f97d32c225b605096203d3bd6360a9c37c327ac172de551324a8c965`
- 117 facts: confirmed 42, inferred 4, unknown 71
- 활성화하지 않았다. parse error 표식도 숨기지 않았다.
- 비공개 원문 후보: `.dryforge/prespec-reference-20260907/company-profile-structured-candidate-v2.md`

이는 새 역량 검증이 아니라 기존 정보의 추출 보완이다. 실제 가용 인력, 등록·인증의
현재 유효성, 실적 증명·역할·지분, 공동수급·상주·수익 조건은 담당자 확인이 필요하다.

## C-1 선정 규칙

새 `screening-policy.sw-business.v1.20260907`을 `activation_candidate`로 저장했다.
`sw-business-selection.v1`은 full_run에서 Y만 선정하며 기존 후보군 밖 Y도 포함한다.
실제 수집본으로 64건, N 0건, 기존 audit_pool 21건 포함을 확인했다.
N은 명시적인 단건 요청 경로를 유지한다. 과거 정책과 고정 품질 표본은 바꾸지 않았고,
새 정책을 운영 활성화하거나 C-1 모델을 실행하지 않았다.

## 검증

- 최종 관련 PostgreSQL·모델 client·개요·첨부·정책·모듈 경계 검사: 228 passed.
- 기존 screening orchestrator 회귀: 34 passed, 기존 부분 성공 결함 2 failed.
  findings에 기록된 동일한 두 테스트이며 새 통과로 보고하지 않는다.
- `./run-tests.sh` 통과(145 tests), 실제 이미지 build 통과.
- 웹 이미지를 재생성하여 수정 적용. API health 및 SW Y 목록 64건 조회 확인.
- 원문과 초기 프로필의 기존 bytes는 보존했다. commit/push는 하지 않았다.

## 최종 결과

| 공고 상태 | 건수 |
| --- | ---: |
| 실제 모델 결과 완료 | 12 |
| 실제 모델 출력 검증 실패 | 2 |
| 프롬프트 한도 초과, 모델 본문 미전송 | 7 |
| 문서 역할·개요 범위 등 사람 확인 필요 | 42 |
| 사용 가능한 원문 대기 | 1 |
| 전체 SW Y 공고 | 64 |

42건 중 현재 snapshot에 사유가 있는 것은 끝 제목 없음 15건, 개요 제목 없음 14건,
구조 경고 1건이다. 나머지 12건은 문서 역할·선택 등의 문제로 current snapshot이 없다.
원문 대기 공고는 `pre:R26BD00269941`이며 조회 API로 `awaiting_document`를 확인했다.

고유 모델 대상 14건에 대해 응답 보관은 15개다(첫 공고 추가 시도 포함).
검증 완료 attempt 13개는 현재 완료 공고 12건과 구별한다. 실패 attempt는
`prompt_rejected` 7개, `evidence_out_of_scope` 1개, `validation_failed` 1개다.
응답 객체 15개의 version ID·암호화 key reference·verified location이 존재한다.
현재 완료 12건의 권고는 추진 검토 3, 보류 6, 검토 종료 3건이며 사람의 결정이 아니다.

첫 공고의 v2 조회를 두 번 연속 수행해 `completed`와 attempt 2개가 유지됨을 확인했다.
최종 상태에 queued/running attempt가 없고 심층 검토는 0건이다.
원문·초기 프로필 SHA-256은 실행 전과 같다.

재시작에 의한 추가 모델 호출을 막기 위해 기존 분석 daemon은 멈춘 상태이며,
이번 실행 container는 유휴 상태다. 이번 작업은 스케줄러나 정책의 운영 활성화가 아니다.
후속은 실패 출력 2건 확인, 한도 초과 7건의 근거 보존 분할 설계, 문서 역할·제목 경계의
사람 확인과 파싱 보완이다. 회사 프로필 후보의 미확인 정보도 심층 검토 전에 확인한다.

비공개 실행 증거: `.dryforge/prespec-reference-20260907/actual/`의
`live-summary-final.json`(원문 대기 공고의 리뷰 생성 전 집계),
`first-overview-final-api.json`, `remaining-overview-preview/`, 개별 구조·cut 파일.
실제 응답 정본은 MinIO, 결과·실패·감사 정본은 PostgreSQL이다.
