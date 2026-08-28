# 프론트엔드 모듈 작업 규칙

## 책임

이 모듈은 React 관리자 화면, REST client와 TypeScript API model, 목록·상세 검토 상태, 실행 진행·실패 표현을 소유한다. 판정 계산, DB·파일 접근, model 호출, 알림 발송은 수행하지 않는다.

## 데이터 경계

- 서버 응답을 브라우저에서 재판정하거나 누락된 등급, 준비 상태, 지표, relation을 계산하지 않는다.
- DB, run 디렉터리, 첨부·객체 경로를 직접 읽지 않는다. 조회와 다운로드는 API URL만 사용한다.
- API error의 human message를 안정 code처럼 분기하지 않는다. endpoint 계열의 typed error shape와 code를 사용한다.
- 모델 provider를 브라우저에서 직접 호출하거나 key, profile, prompt를 bundle에 넣지 않는다.
- 프로필 화면은 API의 승인된 구조화 항목·`unknown`만 사용한다. filesystem source, source line, raw block·raw text, parser 예외을 type이나 UI에 추가하지 않는다.
- TypeScript strict를 유지하고 API payload를 `any`로 우회하지 않는다.

## 상태 표현

- `값 없음`, `미확인`, `계산 불가`, 실제 0을 서로 다르게 표시한다.
- 적합성 등급, 참여 준비 상태, 추적 선택, 최종 Go/No-Go를 별도 필드·라벨·action으로 표시한다.
- 성공, 부분 성공, 실패, 중단, 사람 검토 대기를 서로 구분하고 failure artifact나 재시작 가능 여부를 숨기지 않는다.
- 색만으로 등급, deadline, 차단, delta를 전달하지 않고 문자·아이콘·구조적 표시를 함께 제공한다.
- 담당자 이름은 저장 전에 요구할 수 있지만 로그인이나 신원 인증으로 표현하지 않는다.
- 외부 모델 보조 실행은 전송 필드와 payload 미리보기, 대상 모델, 승인 action 없이는 시작할 수 없게 한다. 허용 payload는 공개 발주계획 metadata와 별도 승인된 최소 회사 역량 요약뿐이다. RFP·첨부, profile 전문, evidence, 내부 review·실적은 preview 후 사람이 승인해도 외부 전송 action을 활성화하지 않는다.

## 검토 흐름

- 목록 필터는 URL과 동기화하고 선택한 항목, 상세 scroll, 저장 후 이동을 예측 가능하게 유지한다.
- 자동 연결 실행과 단계별 수동 실행은 같은 execution 상태 컴포넌트를 사용한다. 별도 상태 의미를 복제하지 않는다.
- 문서 준비 화면은 upload, scan, convert, structure, bundle confirm을 구분하고 실패 stage와 안전한 retry action을 보여야 한다.
- 심층 검토 실패 재시작은 기존 attempt를 덮지 않으며 새 attempt가 생긴다는 점을 확인시킨다.
- 향후 opportunity 화면은 plan, pre-spec, bid의 공식 연결과 사람 확인 대기 후보를 시각적으로 구분한다.
- 사전규격 보고서 뒤 `계속 추적|보류|종료`와 입찰공고 뒤 최종 `Go/No-Go`를 같은 버튼 집합으로 재사용하지 않는다.

## UI 패턴

- TanStack Query로 서버 상태를 조회하고 mutation 성공 뒤 영향 query만 무효화한다.
- 밝은 중립 표면, 8px 간격 단위, 20~24px 카드 여백, 40~44px 조작부의 실무형 계층을 유지한다.
- 공고 목록과 상세 정보 밀도를 유지한다. 마케팅식 큰 여백, 장식 아이콘, gradient, glass effect를 사용하지 않는다.
- 긴 한글 제목, 표의 긴 요구사항, 좁은 화면, keyboard focus, empty/loading/error 상태를 설계한다.

## 검증

```bash
cd web/frontend
npm run build
npm run test:visual
```

TypeScript strict, production bundle, 기본 필터, null/0 표시, 부분 실패, review 저장과 다음 이동, API 오류, empty/loading, 긴 한글, 좁은 viewport, keyboard focus를 확인한다. 외부 font network 없이 visual 결과가 재현되어야 한다.
