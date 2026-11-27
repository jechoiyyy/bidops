# 2026-11-24 추적 시작 → 분석 요청 → 승인 — 격리 스택 시운전

[개정안](../../work/groups/RL/features/RL-11-live-prespec-engine/track-start-entry.md)(ADR-0078)의 1~3단계 기록이다. 브랜치 `feat/rl11-track-start-entry`(복제본 `/Users/temp/orca/bidops-rl11b`), main `a847ec0` 기준. **엔진 실행은 전부 `mock_reference`이고 외부 모델 전송은 0건이다.** 품질·운영 활성화의 근거가 아니며 운영에는 아무것도 적용하지 않았다.

## 검증 요약 (감독 실행)

| 대상 | 환경 | 결과 |
|---|---|---|
| 백엔드 전체 스위트 (1단계 직후) | 운영 이미지 런타임 + PostgreSQL 17.11, 깨끗한 복제본 | 4,298 통과 · 199 실패. [main 기준선](../20261124-company-wiki-backend/README.md)에 없던 실패 11건: 업무량 키 목록 7(응답에 두 건수 추가), DB head·테이블 수 고정값 2, 앞 검사 실패가 설정 캐시를 남긴 순서 의존 2 |
| 위 11건 재실행 | 같은 환경, 원래 순서 | 228 통과 |
| 시운전 뒤 수정분의 영향 범위 | 같은 환경 | 113 통과 · 12 실패(모두 기준선의 낡은 검사) |
| 화면 `engine-review.spec.ts` | Playwright, mock API | 36 통과 |
| 화면 전체 | Playwright 4개 프로젝트 | 1,120 통과 · 4 실패 → 새 검사 3건을 고친 뒤 그 파일 36 통과. 남은 1건 `route-context.spec.ts:281`(입찰 변경 화면의 목록 복귀)은 전체 실행에서 두 번 실패하고 단독으로는 통과한다 — 잠깐 지나가는 주소를 기대하는 기존 경합이며 이번 변경이 건드리지 않은 화면이다. 고치지 않았다 |

전체 백엔드 스위트는 수정 뒤 다시 돌리지 않았다(수정이 검사 기대값·주석·영향 범위가 좁은 코드라 해당 파일만 재실행).

## 격리 스택

- `COMPOSE_PROJECT_NAME=bidops-rl11trial BIDOPS_ENV=mock scripts/compose.sh …`, web `127.0.0.1:18796`(tailnet `:8186`). postgres·minio·clamav·document-worker 2·web·analysis-worker. 운영 스택과 프로젝트·볼륨·네트워크가 다르다.
- 이미지 `bidops-rl11trial:app`: 이 브랜치를 `docker/Dockerfile`로 빌드(시운전용, 배포 대상 아님).
- 설정(`env/mock.env`, Git 밖): 개발용 자격 + `BIDOPS_ENGINE_REVIEW_MODE=mock_reference`, `BIDOPS_ENGINE_ANALYSIS_ENABLED=true`, 회사 묶음 슬러그 `rootlab`. 위키는 운영 정본의 사본을 붙였다.
- 데이터: 2026-11-23 공고 수집 회차의 읽기 전용 사본을 `--collection`으로 적재(사전규격 99건·입찰공고 253건). **회사·프로필·바인딩 0행.**
- 격리 스택은 나라장터에서 첨부를 받을 수 없어 보관 중인 제안요청서 3건(HWPX 2·HWP 1)을 `attach-local-original`로 붙였다. **공고와 다른 사업의 문서다** — 흐름 확인용이며 내용 대조는 의미가 없다.

## 한 일과 결과 (실제 서버, 가짜 응답 없음, 브라우저 조작)

| 단계 | 결과 |
|---|---|
| 상세에서 `추적 시작하기` | `PATCH tracking-status` 200 → 분석 요청 등록(`origin: tracking_start`), 상태 `preparing / documents_pending` |
| 원문 붙이기 | ClamAV `clean`, 문서 worker 변환, 묶음 자동 확정 → `awaiting_approval`, 업무량 `engine_approval_pending` 1 |
| `전송 자료 확인` → `승인` | 미리보기 발급 → 승인 영수증과 엔진 실행·작업이 함께 생성 → worker가 mock 실행 → `result_ready`(`partial`, `mock_reference`, 입력 v3, `company_id: null`, 묶음 `rootlab`·digest `3cfc71557050…`) |
| 결과 화면 | 결과 표시 → `계속 추적` + 사유 저장(추적 감사 1건) → `읽음으로 표시` → `acknowledged`. 추적 상태는 사람이 누른 대로만 바뀌었다 |
| 일괄 추적 시작 2건 | `bulk-start` 둘 다 `started` → `requests:batch` 둘 다 `requested`. 승인·실행 0 |
| `이번엔 보내지 않음` | 요청 닫힘 → `not_requested / request`(다시 요청 가능) |
| 스위치 | `GET /api/feature-flags` → `engine_review: "mock_reference"`. Compose가 web·worker 둘 다에 값을 넘긴다 |

최종 기록: `engine_review.requested` 3 · `.preview_created` 3 · `.approved` 1 · `.dismissed` 1 · `.closed` 1 · `.acknowledged` 1, `engine_run` 1(`mock_reference`), 열린 요청 2 · 닫힌 요청 1, `opportunity.tracking_status.changed` 4(모두 사람).

캡처는 [`shots/`](shots/): 추적 시작 전·후, 승인 대기, 전송 자료 확인(1440·1280), 결과(1440·1280), 일괄 대화상자, 건너뛰기 뒤, 오늘 할 일.

## 시운전에서 찾아 고친 것

- **Compose가 스위치를 컨테이너에 넘기지 않았다.** 단위 검사로는 드러나지 않았다. web·worker에 `BIDOPS_ENGINE_REVIEW_MODE`·`BIDOPS_ENGINE_ANALYSIS_ENABLED`를 연결하고, 운영 구성에서 `mock_reference`이면 기동이 실패하게 했다.
- **전송 자료 확인이 절 목록에 묻혔다.** 실제 문서는 절이 60~96개라 요약과 `승인`이 화면 밖으로 밀렸다. 요약을 앞에 두고 단추를 바닥에 고정했으며 절 목록은 접었다.
- **문서 쪽 수가 3으로 나왔다.** HWPX 추출기의 XML 구역 수였다. HWP/HWPX는 쪽 수·절 쪽 범위를 `null`(미확인)로 낸다.
- **결과 경고에 내부 code가 그대로 나오고 중복됐다.** 업무 문장으로 바꾸고 원문 code는 접힌 기술 정보로 옮겼다.
- **`읽음으로 표시` 줄이 본문을 가렸다**, **`추적 결정` landmark가 둘이었다**, **저장 문구가 두 줄로 접혔다.**
- **요청 뒤에도 문서 준비 카드가 "자동 문서 준비 대상이 아니에요"였다.** 요청 성공 뒤 화면이 사전규격 조회를 다시 읽지 않았다. 조회를 무효화하고 사유 `engine_review_request`("분석 요청으로 원문을 준비하고 있어요")를 더했다.

## 남은 것

- 목차의 제목과 본문 제목이 절 목록에 함께 들어온다. 추출된 블록 정보로는 구별할 근거가 없어 그대로 두었다(접힌 목록 안).
- 전송 자료 확인의 수신 줄이 `mock_reference · mock_reference`로 보이고 위키 페이지가 슬러그로 나온다.
- 실제 분석 경로(4단계: 단계 IPC, Luna 계약, 호출별 감사, 호출 예산, C-2 양보)와 감독 시운전·사람 인수(5단계)는 시작하지 않았다. 엔진 실행은 `single`(3회 호출) 고정이고 명세의 장문 예시는 12회 계획이라 호출 상한(8회)과 분할 방식을 4단계에서 정해야 한다.
- 실제 나라장터 첨부 취득 → 분석 요청의 연결은 이 스택에서 돌지 않았다(첨부를 수동으로 붙였다). 운영의 첨부 worker와의 연결은 운영에 올리기 전 감독 시운전에서 확인해야 한다.
- main은 이 브랜치가 갈라진 뒤로 더 나아갔고 다른 작업이 사전규격 상세(`PreSpecDetailPage.tsx`)를 고치고 있다. 합칠 때 충돌을 풀어야 한다.

## 스택 내리기

`cd /Users/temp/orca/bidops-rl11b && COMPOSE_PROJECT_NAME=bidops-rl11trial BIDOPS_ENV=mock scripts/compose.sh down`(볼륨 삭제는 사람이 확인하고 따로), tailnet 노출 해제 `tailscale serve --tcp=8186 off`.
