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
- 실행의 품질 표식(`quality_status`)은 네 상태다. `측정 통과`·`참조 실행 · 품질 미측정`·`mock 참조`·`표식 없음`(값이 `null`). **참조 실행과 mock을 운영 완료처럼 보이게 하지 않고, `표식 없음`을 미측정이나 측정으로 바꾸지 않는다.** 이 셋은 성공도 실패도 아니므로 성공·실패 의미색을 쓰지 않는다.
- 사전규격의 `grade`가 `null`이면 `판정 없음`이고 출처는 `등급 출처 · 판정|정정|없음`으로 따로 적는다. 등급 없음을 특정 등급으로 접지 않는다.
- `auto_preparation_reason`은 서버가 정한 안전 코드다. 화면에 문장이 있는 코드만 번역하고 **모르는 코드는 그대로 보여 준다.** 임의로 다른 사유로 바꾸거나 숨기지 않는다.
- 적합성 등급, 참여 준비 상태, 추적 선택, 최종 Go/No-Go를 별도 필드·라벨·action으로 표시한다.
- 성공, 부분 성공, 실패, 중단, 사람 검토 대기를 서로 구분하고 failure artifact나 재시작 가능 여부를 숨기지 않는다.
- 색만으로 등급, deadline, 차단, delta를 전달하지 않고 문자·아이콘·구조적 표시를 함께 제공한다.
- 담당자 이름은 저장 전에 요구할 수 있지만 로그인이나 신원 인증으로 표현하지 않는다.
- 외부 모델 보조 실행은 전송 필드와 payload 미리보기, 대상 모델, 승인 action 없이는 시작할 수 없게 한다. 허용 payload는 공개 발주계획 metadata와 별도 승인된 최소 회사 역량 요약뿐이다. RFP·첨부, profile 전문, evidence, 내부 review·실적은 preview 후 사람이 승인해도 외부 전송 action을 활성화하지 않는다.

## 검토 흐름

- 목록 필터는 URL과 동기화하고 선택한 항목, 상세 scroll, 저장 후 이동을 예측 가능하게 유지한다.
- **서버가 거르지 못하는 필터는 그 사실을 화면이 밝힌다.** `/pre-specs?grade=<값>`은 `GET /api/pre-specs`에 대응 질의 인자가 없어 이미 받은 페이지만 좁히는 브라우저 쪽 필터다. 같은 화면의 `overview_status_counts`는 필터 이전 전체 집합을 가리키므로 두 수를 같은 뜻으로 읽히게 두지 않는다. 허용 값은 `우선 검토|검토 권장|관찰 대상|제외|판정 없음`이고 그 밖의 값은 `전체`로 떨어지며, `grade`를 바꾸면 `offset`을 초기화한다.
- 계약에 없는 값을 화면이 채우지 않는다. 보고서의 segment 패널은 묶음에서 문서들의 `structure_id`를 얻을 endpoint가 없어 **선택된 근거가 가리키는 문서 하나**만 보여 주며, 그 사실을 문장으로 적는다. segment에는 wire 상 제목이 없으므로(원문 text를 싣지 않기로 한 결정의 결과) ordinal·taxonomy label·요구사항 id·`block_key`·page 링크만 보이고 제목이 없는 이유를 적는다.
- 자동 연결 실행과 단계별 수동 실행은 같은 execution 상태 컴포넌트를 사용한다. 별도 상태 의미를 복제하지 않는다.
- 문서 준비 화면은 upload, scan, convert, structure, bundle confirm을 구분하고 실패 stage와 안전한 retry action을 보여야 한다.
- 심층 검토 실패 재시작은 기존 attempt를 덮지 않으며 새 attempt가 생긴다는 점을 확인시킨다.
- 향후 opportunity 화면은 plan, pre-spec, bid의 공식 연결과 사람 확인 대기 후보를 시각적으로 구분한다.
- 사전규격 보고서 뒤 `계속 추적|보류|종료`와 입찰공고 뒤 최종 `Go/No-Go`를 같은 버튼 집합으로 재사용하지 않는다.

## UI 패턴

- TanStack Query로 서버 상태를 조회하고 mutation 성공 뒤 영향 query만 무효화한다.
- 색은 `bidops` 테마(무드보드 파생, ADR-0048)가 정본이다. 화면은 토큰만 읽고 `:root`나 화면 CSS에서 `--color-*`를 재정의하지 않는다. 유일한 예외는 `styles/shell-relaxed.css`의 이행용 token bridge이며 새 색 값을 만들지 않는다. 색을 바꾸려면 `src/themes/bidops/bidopsTheme.ts`를 고치고 `astryx theme build`를 다시 돌린다.
- Tailwind `@theme`에 디자인 시스템과 이름이 겹치는 `--color-*`를 추가하지 않는다. `@theme`은 `:root`로 방출돼 `@layer astryx-theme`을 이기므로 테마 값이 조용히 무시된다([engineering-notes.md](../../docs/engineering-notes.md)).
- 공고 목록과 상세 정보 밀도를 유지한다. 마케팅식 큰 여백, 장식 아이콘, gradient, glass effect를 사용하지 않는다.
- 긴 한글 제목, 표의 긴 요구사항, keyboard focus, empty/loading/error 상태를 설계한다. 지원 폭은 1280~1920px이며 모바일·태블릿 레이아웃을 만들지 않는다(ADR-0047). 1280px 미만은 가로 스크롤로 둔다.

## 검증

```bash
cd web/frontend
npm run build              # tsc -b + vite build
npm run test:contrast      # 테마 대비 게이트 (ADR-0048)
npm run test:screens       # 화면 게이트 — 의미(한 폭) + 구조(두 폭)
npm run test:design        # 셸 구조·색·치수만 따로
npm run test:pixel         # 기준 이미지 대조 — 게이트 아님
```

TypeScript strict, production bundle, 기본 필터, null/0 표시, 부분 실패, review 저장과 다음 이동, API 오류, empty/loading, 긴 한글, keyboard focus를 확인한다. 외부 font network 없이 결과가 재현되어야 한다.

화면 검사는 의미·구조·픽셀 세 층이고 층마다 실패의 뜻이 다르다. 표와 각 층의 규칙은 [`docs/standards.md`](../../docs/standards.md)의 "화면 검사의 세 층"에 있다. **게이트는 `test:screens`까지이고 픽셀 층은 게이트가 아니다.** 픽셀이 깨졌다는 것은 "화면이 틀렸다"가 아니라 "지난 기준선과 달라졌다"는 뜻이므로, 의도한 변경이면 `npm run test:pixel:update`로 갈아 끼우고 **사유·영향 화면·승인자를 기록에 남긴다.**
