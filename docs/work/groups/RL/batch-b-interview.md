# RL 배치 B(RL-03·RL-04) 시작 인터뷰 — 2026-10-17

배치 A(run `rla-20261016`, RL-00~02) main 반영(9c61fe1) 뒤 사용자 요청: "RL-03,04를 진행하기 위한 것들을 정리해서 인터뷰형식으로 정해서 바로 시작할 수 있도록 하자". 사용자는 배치 B(실제 Luna 호출 포함)를 승인했다. 아래 값이 배치 B의 승인 범위·전송 정책·상한·정지 조건이다. 사전 조사는 RL-03·04 intent·spec·plan, ADR-0073·0069, `docs/0922_luna-deep-review/apply.md`, 로컬 runner·fixture·bidops-local 상태를 읽기 전용으로 확인했다.

## 사용자 답 (2026-10-17)

| # | 질문 | 답 | 반영 |
|---|---|---|---|
| D1 | 판정 전제 "개요 run completed"(개요는 LiteLLM/vLLM 경로 = RL 제약 위반, Luna 개요 코드는 폐기 브랜치) | **개요 조건 제거** | RL-03 spec: 트리거·수동 요청 조건에서 개요 완료를 빼고 공고 메타 `sw_business_status='Y'` + 문서 묶음 ready로 대신. 판정 입력의 `overview_*` 의존 제거. Luna 호출은 판정 단계만 |
| D2 | Luna로 보낼 회사 자료 범위 | **확인된 사실 전부** | `confirmed` 사실 전부(자격·실적·인력·선호/제외·`pref:*` 금액·컨소시엄·하도급 조건 포함). `proposed`·`unknown`은 **값 없이 fact_key·status만**. 노트·운영 정보·모델/정책 id는 제외. 공고 원문 unit(카드 + 여섯 영역)은 포함 |
| D6 | Luna 인증 계정 | **개인 로그인 그대로** | runner가 호스트 `~/.codex/auth.json`(CLI 0.162.1)을 읽기 전용 마운트. 값·파일 내용은 로그·문서에 남기지 않음 |
| D3·D4·D10 | 실제 호출 상한·실패 대응 | **증명 2건 + 재시도 1회** | 실제 호출은 RL-03 T12(폴리텍 사전규격 판정 1건, 최대 약 24회 호출)와 RL-04 T11(그 판정으로 초안 1건, 최대 12회)뿐. 자동 트리거는 실제 스택에서 **꺼 둔다**(자동 트리거 검증은 mock). T12가 검증 실패면 **1회만** 다시 시도, 그래도 실패면 RL-04 T11 보류하고 보고. 자동 재시도·자동 보정 없음 |
| D7 | runner egress | **현재 bridge 허용** | 로컬 Mac PoC에서 runner만 외부 통신(`luna-egress`). web·worker는 내부망. 앱의 전송 승인·payload 검사·감사는 그대로 |
| D8 | 폴리텍 첨부 취득 | **로컬 원본 사용** | `~/orca/fixtures/RFP/`의 원본 HWP(이전 수집본과 sha 일치)를 격리 DB에 등록. 나라장터 호출 없음 |
| D13 | 회사 unknown 21건 보강 | **그대로 진행** | 루트랩 v2로 판정. "확인 필요"가 많은 것은 데이터 상태로 기록. 보강은 RL-05 전 인터뷰 |
| D9 | 범위·형식 | **spec대로** | RL-03은 사전규격만(입찰공고는 후속). RL-04는 PDF 6절, 이미지의 NanumGothic(저장소에 폰트 파일 추가 없음) |

## 리더 권장안으로 정한 것 (사용자 지시: 선택은 권장안으로 진행하고 기록)

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| D5 | Slack 스레드 기록 | 토큰이 없으므로 가짜 서버 검사까지만. `slack_message_ts`가 없으면 답글은 건너뛰고 실제 Slack 증명으로 적지 않음 | 배치 A와 같은 원칙 |
| D11 | 감사·CLI 담당자 이름 | `jechoi` | git 사용자, 이전 실행과 같음 |
| D12 | 초안 PDF 보관 | spec 값(365일, 암호화 없음) 유지, 격리 스택에서만 생성 | spec 결정, 운영 반영은 별도 |
| — | `reportlab` 의존성 | PyPI에서 wheel hash를 받아 lock에 고정(개발 의존성 취득용 네트워크만, 데이터 전송 아님) | 배치 A `slack_sdk`와 같은 절차 |
| — | spec 결함 정정 | RL-03: `qual:branch`는 `value.detail` 읽기, `staff:design_publishing`은 `available` 읽기(`total` null), payload의 proposed/unknown은 값 없이(D2). RL-04: tech-stack 폰트 문구·REST 개수(8)·"OFL 폰트 2종" 위험 문구를 결정에 맞춤 | 실제 fixture 모양·D2·D9와 일치 |

## spec 개정 중 추가 결정 (리더 권장안, 2026-10-17)

| 항목 | 결정 | 근거 |
|---|---|---|
| 실제 호출 상한을 코드로 강제 | RL-03 정책 `--daily-cap 2`(T12 + 재시도 1), RL-04 `--daily-cap 1` | D3·D10을 운영 규칙이 아니라 기존 CLI 범위 안의 값으로 고정 |
| RL-04 `missing_facts` | `{fact_key, status}`만(라벨 제외) | D2 문구 그대로 |
| RL-04 실제 전송 payload | 절 생성에 필요한 8키만 보내고 식별·운영 키는 동결 입력에만 | D2를 검사 가능하게 |
| RL-03 총 인력 대조값 | `staff:total.value.total`(회사소개서 confirmed 58) 사용, 분야 합산(35) 대신 사용 안 함 | 분야 노드 합은 디자인·상주 등을 빠뜨려 과소 집계 |
| 남은 문서 수치 불일치(RL-04 오류 code 개수 문구, RL-03 contracts 요약 개수) | 구현 단계 문서 개정(STEP 문서)에서 실제 값으로 맞춤 | 계약 내용 변화 없음 |
| requirements.lock 플랫폼 | 배치 A와 같이 linux/amd64 lock + Mac에서 `--platform linux/amd64` 빌드 | 기존 절차 |

## 정지 조건 (배치 A와 같음 + 외부 전송)

- 같은 단계 재시도 1회 뒤에도 검증 실패 / 모듈 경계·권한·alembic drift 실패 / spec에 없는 테이블·REST·설정 키 필요 / 문서 밖 회사 사실 필요.
- 승인 감사(`analysis.transfer.sent`) 없는 전송, payload에 노트·proposed/unknown 값·운영 정보가 들어감, 상한 초과 → 즉시 중단·보고.
- 실제 호출 직전·정책 승인 CLI·runner 재배포·bidops-local 스택 변경 때는 짧게 알리고 진행(이 인터뷰가 범위 승인). 운영 `bidops` 스택·운영 DB·cron·origin push 금지.
- 결과는 `unmeasured_reference`로만 기록하고 품질 근거로 쓰지 않음. 실패 결과는 사람 검토로 보내며 자동 보정하지 않음.
