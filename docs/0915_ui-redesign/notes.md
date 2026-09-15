# Notes: 관리 화면 재설계 (C 기준) — 재발 방지 — 기준일 2026-09-15

이 폴더는 이전 `docs/` 문서 체계와 독립이다. 이 문서는 [`plan.md`](plan.md) P4
4번이 정한 재발 방지 사실 5개와, P1~P3 구현 중 spec에서 벗어나 확정한 사실을
적는다. `decisions.md`가 다루지 않는 구현 세부만 여기 둔다.

## 재발 방지 다섯 가지

1. **`#75A03B`(`--bo-brand`)는 글자에도, 흰 글자를 얹는 채움에도 쓰지 않는다.**
   흰 카드 위 3.07:1, 회녹 canvas(`#F6F7F4`) 위 2.85:1이라 어느 쪽도 텍스트
   4.5:1을 만족하지 않는다. `check-contrast.test.mjs`의 비텍스트 pair도
   `['bo-brand', 'color-background-card']`(카드 기준, 3.07:1)만 넣었다 —
   canvas 기준 pair는 2.85:1로 3:1 미만이라 뺐다. 라벨을 동반한 비텍스트
   표시(진행 막대 채움, 완료 단계 번호 배경, 밑줄 탭 등)만 흰 카드 위에서 쓴다.
   근거: `web/frontend/src/themes/bidops/brand.css:8`,
   `web/frontend/scripts/check-contrast.test.mjs:80-82`.
   브랜드 줄 C안 채택으로 `--bo-brand` 위 글자는 없다 — 브랜드 줄은 면 없이
   아이콘·워드마크와 부제만 얹는다(짧은 포인트 선은 2026-09-16 사용자 요청으로 뺐다). 근거:
   `web/frontend/src/styles/shell-relaxed.css:147-153`.

2. **새 색은 `--bo-*` 프로젝트 토큰(`brand.css`·`grade-ramp.css`)에만 둔다.**
   Astryx의 `TokenName`이 `CoreTokenName | DomainTokenName` 닫힌 union이라
   테마(`bidopsTheme.ts`)에 새 토큰 이름을 넣으면 CLI는 emit해도 `tsc -b`가
   TS2353으로 거부한다. 근거: `web/frontend/src/themes/bidops/grade-ramp.css:4-6`,
   `web/frontend/src/themes/bidops/brand.css:4-5`,
   `web/frontend/src/themes/bidops/bidopsTheme.ts:162-163`.

3. **`src/styles/theme.css`의 Tailwind `@theme`은 `:root`로 방출돼 테마를
   이긴다.** `@layer astryx-theme`보다 먼저 적용되므로 같은 이름을 거기 남기면
   테마가 정한 값이 앱 안에서 절대 적용되지 않는다(`theme.css:22-24`의 주석대로
   `--color-border`는 이미 이 이유로 제거돼 있다). `design-shell.spec.ts`가
   `--color-border`·`--color-success` 두 토큰을 `:root`에서 읽어 감시한다.
   근거: `web/frontend/src/styles/theme.css:11,22-24`,
   `web/frontend/tests/design-shell.spec.ts:114-116`.

4. **사이드바가 더는 `--color-on-dark`를 읽지 않는다.** 사이드바 배경이
   `--color-background-inverted`(어두운 면)에서 `--color-background-body`(흰
   canvas와 같은 밝은 면)로 바뀌어, 사이드바 본문 글자는 `--color-text-secondary`
   를 읽는다. `--color-on-dark`·`--color-background-inverted`는 `.ps-chip-dark`·
   실행 단계 번호 등 어두운 면 전용으로만 남는다. 근거:
   `web/frontend/src/styles/shell-relaxed.css:3-8`.

5. **`bidops.css`는 빌드 산출물이라 손으로 고치지 않는다.** 파일 머리의 생성
   주석이 명령을 적는다: `astryx theme build src/themes/bidops/bidopsTheme.ts
   --out src/themes/bidops/bidops.css`(레포 실행은
   `npx @astryxdesign/cli theme build …` 형태). 값을 바꾸려면 `bidopsTheme.ts`를
   고치고 다시 빌드한다. 근거: `web/frontend/src/themes/bidops/bidops.css:1-6`.

## P1~P3 구현 중 확정된 spec 이탈

- **비활성 보기 탭 글자는 `--color-text-disabled`가 아니라
  `--color-text-secondary`.** spec §2.2 원문은 비활성 탭(건수 포함)을 전부
  `--color-text-disabled`(canvas 위 2.2:1)로 적었으나, 비활성 탭도 누를 수 있는
  조작이라 4.5:1을 지켜야 한다. 같은 위계에서 가장 진한 값인 secondary(7.2:1)를
  라벨에 쓰고, 건수만 disabled 색으로 남긴다(spec §2.2를 이 사실로 고쳤다).
  근거: `web/frontend/src/styles/workspace-filters.css:72-75,99`.
- **목록 우측 영역 머리(①)는 `.pre-specs-detail-scroll` 밖에 있다.** 여백
  계약을 유지하려 1행만 스크롤 밖에 고정하고 2~7행이 스크롤 컨테이너 안에
  있다. 상세 진입 단추 이름은 `상세 페이지 열기 →`, 주의 줄 활성 바탕은
  `--color-background-orange`(`.pre-specs-detail-caution.is-caution`)다.
  근거: `web/frontend/src/components/pre-specs/PreSpecListDetailPane.tsx:198,235,373`,
  `web/frontend/src/styles/pre-specs-relaxed.css:727-742`.
- **상세 ⑥의 접힌 줄 이름은 `현재 주장 검증 진단 · 고정 입력과 식별 해시`.**
  spec §4 ⑥ 원문의 `· 회사 적합성 실행 정보`는 붙이지 않았다 — 회사 적합성
  실행 정보는 ④ 열이 갖는다. `현재 v4 개요 실행`(`PageOverviewCurrent`)과
  `이전 개요 결과`(`PageOverviewHistory`)는 접지 않고 `처리 이력` 블록에 펼쳐
  둔다. 이유: Astryx `Collapsible`은 닫혀 있을 때 `display:none`으로 감춰
  role 조회로 값을 확인할 수 없기 때문이다. 근거:
  `web/frontend/src/pages/PreSpecDetailPage.tsx:864-865,897-916,931-944`.
- **상세 완료 단계 번호는 `--bo-brand` 배경 + `--color-text-primary` 글자.**
  `--bo-brand` 위에는 흰 글자를 얹지 않는다는 규칙(1번)을 완료 단계 번호에도
  적용해, 번호 글자는 본문 색을 쓴다. 근거:
  `web/frontend/src/styles/pre-spec-detail-erp.css:557-558`.
- **첨부 크기 표기는 `2,400,000 B` 형식을 유지한다.** 시안의 `2.4 MB` 표기는
  채택하지 않았다 — 바이트 값을 화면에서 다시 계산(단위 변환)하지 않는다는
  제약을 따른다. 근거:
  `web/frontend/src/components/pre-specs/PreSpecAttachmentList.tsx:23,46`.
- **상단바 경로 leaf는 아직 `notice {id}`다.** `route-meta.ts`의 상세 record
  칸이 route param(`noticeId`)만 읽어 `notice ${value}`를 만든다. spec §4의
  `{pre_spec_no|번호 미확인}` 표기는 미구현이다. 후속 과제로 남긴다. 근거:
  `web/frontend/src/components/shell/route-meta.ts:185`.
- **파비콘은 `web/frontend/public/favicon.svg`다.** `#75A03B` 둥근 사각(rx 9) +
  `rootlab-icon-light.svg`의 아이콘 영역(x<45) path만 흰색으로 올렸다. `index.html`
  `<head>`가 이 파일을 `image/svg+xml`로 가리킨다.
- **`docs/0915_ui-redesign/mockups/shots/Main.png`은 옛 캔버스 판이다.**
  이 PNG의 사이드바는 흰색·좌측 바가 있는 구성이지만, 구현 정본인
  §2.1(셸이 흰 카드 + `--shadow-low`로 활성을 말하고 좌측 바는 없음)과
  아트보드(`mockups/artboards/Main.dc.html`)가 이긴다. `decisions.md`의
  "팔레트·토큰" 항목도 같은 사실을 적는다.
