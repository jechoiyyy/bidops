/**
 * bidops 테마 대비 게이트 — ADR-0047 결정 5, docs/design/PRD.md §4.1.
 *
 * 무드보드 anchor 는 색을 제안하고 대비비가 그것을 이긴다. 이 검사는 빌드된
 * bidops.css 에서 실제 토큰 값을 읽어 검증하므로, 테마 정의를 고치고 다시
 * 빌드하지 않으면 통과하지 않는다.
 *
 * neutralTheme.ts 주석이 가리키는 upstream `check-badge-contrast.test.mjs` 는
 * 이 저장소에 없다. 이 파일이 그 역할을 대신한다.
 *
 *   node --test scripts/check-contrast.test.mjs
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const css = readFileSync(join(root, 'src/themes/bidops/bidops.css'), 'utf8');
// 등급 ramp 는 Astryx TokenName 이 닫힌 union 이라 테마가 아닌 프로젝트 토큰이다.
const rampCss = readFileSync(join(root, 'src/themes/bidops/grade-ramp.css'), 'utf8');

/** 빌드된 CSS 에서 토큰의 라이트 모드 값을 읽는다. */
function token(name) {
  const source = name.startsWith('bo-') ? rampCss : css;
  const where = name.startsWith('bo-') ? 'grade-ramp.css' : 'bidops.css';
  const re = new RegExp(`--${name}:\\s*(?:light-dark\\(\\s*([^,]+?)\\s*,[^)]*\\)|(#[0-9a-fA-F]{3,8}))\\s*;`);
  const m = source.match(re);
  assert.ok(m, `토큰 --${name} 을 ${where} 에서 찾지 못했다. 테마를 다시 빌드했는가?`);
  return (m[1] ?? m[2]).trim();
}

function luminance(hex) {
  const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** 텍스트 — WCAG AA 4.5:1 */
const TEXT = [
  ['color-text-primary', 'color-background-body'],
  ['color-text-primary', 'color-background-card'],
  ['color-text-secondary', 'color-background-body'],
  ['color-text-secondary', 'color-background-card'],
  ['color-text-secondary', 'color-background-muted'],
  ['color-text-accent', 'color-background-body'],
  ['color-text-accent', 'color-background-card'],
  ['color-on-accent', 'color-accent'],
  // 사이드바: 라이트 모드 안의 어두운 surface
  ['color-on-dark', 'color-background-inverted'],
];

/**
 * 비텍스트 중 **컴포넌트·상태를 식별하는** 요소 — WCAG 1.4.11, 3:1.
 * 카드 테두리·구분선·skeleton 은 장식이라 이 목록에 넣지 않는다(upstream
 * neutral 테마도 그것들을 3:1 로 잡지 않는다).
 */
const NON_TEXT = [
  ['color-icon-primary', 'color-background-body'],
  ['color-icon-secondary', 'color-background-body'],
  ['color-icon-secondary', 'color-background-card'],
  ['color-icon-accent', 'color-background-body'],
  ['color-accent', 'color-background-body'],
];

/** 적합성 등급 ramp — 배경과 그 위 라벨. 의미색이 아니라 농도 순서다. */
const GRADES = [
  ['bo-grade-1', 'bo-on-grade-1'],
  ['bo-grade-2', 'bo-on-grade-2'],
  ['bo-grade-3', 'bo-on-grade-3'],
  ['bo-grade-4', 'bo-on-grade-4'],
  ['bo-grade-none', 'bo-on-grade-none'],
];

test('텍스트 토큰이 WCAG AA(4.5:1)를 만족한다', () => {
  for (const [fg, bg] of TEXT) {
    const r = ratio(token(fg), token(bg));
    assert.ok(r >= 4.5, `--${fg} on --${bg} = ${r.toFixed(2)}:1 (4.5 필요)`);
  }
});

test('컴포넌트를 식별하는 비텍스트 요소가 3:1을 만족한다', () => {
  for (const [fg, bg] of NON_TEXT) {
    const r = ratio(token(fg), token(bg));
    assert.ok(r >= 3, `--${fg} on --${bg} = ${r.toFixed(2)}:1 (3.0 필요)`);
  }
});

test('등급 ramp 4단과 판정 없음이 라벨 대비를 만족한다', () => {
  for (const [bg, label] of GRADES) {
    const r = ratio(token(label), token(bg));
    assert.ok(r >= 4.5, `--${bg} 위 라벨 --${label} = ${r.toFixed(2)}:1 (4.5 필요)`);
  }
});

test('등급 ramp는 색만으로 구분되지 않으므로 라벨을 동반해야 한다', () => {
  // 인접 단의 배경 대비가 3:1 미만임을 고정해 둔다. 이 사실이 바뀌면
  // PRD §4.1 의 "항상 텍스트 라벨을 동반한다" 근거도 다시 써야 한다.
  const ramp = ['bo-grade-1', 'bo-grade-2', 'bo-grade-3', 'bo-grade-4'];
  const adjacent = ramp.slice(0, -1).map((g, i) => ratio(token(g), token(ramp[i + 1])));
  assert.ok(
    adjacent.every((r) => r < 3),
    `인접 단이 3:1 이상으로 벌어졌다(${adjacent.map((r) => r.toFixed(2)).join(', ')}). PRD §4.1 근거를 재검토할 것`,
  );
});

test('cool gray anchor(#8D8F8E)가 텍스트 토큰에 배정되지 않는다', () => {
  // 흰 배경 3.25, greige canvas 위 2.87, greige anchor 위 2.08 로 AA 미달이다.
  // disabled 는 WCAG 대비 요구에서 제외되므로 유일하게 허용한다.
  const offenders = [...css.matchAll(/--(color-text-[a-z-]+):\s*(?:light-dark\(\s*)?(#8[dD]8[fF]8[eE])/g)]
    .map((m) => m[1])
    .filter((name) => name !== 'color-text-disabled');
  assert.deepEqual(offenders, [], `#8D8F8E 가 텍스트 토큰에 배정됐다: ${offenders.join(', ')}`);
});

test('의미색은 무드보드가 정하지 않는다 — neutral 값을 유지한다', () => {
  // ADR-0047 결정 4. 실패·경고가 팔레트 톤에 묻히지 않아야 한다.
  for (const [name, expected] of [
    ['color-success', '#007004'],
    ['color-error', '#a50c25'],
    ['color-warning', '#745b00'],
  ]) {
    assert.equal(
      token(name).toLowerCase(),
      expected,
      `--${name} 이 바뀌었다. 의미색 변경은 ADR-0047 결정 4 를 다시 열어야 한다`,
    );
  }
});
