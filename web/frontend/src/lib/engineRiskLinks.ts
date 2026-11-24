const tokenPattern = /[0-9][0-9,.]*\s*(?:명|건|일|개월|년|%|원)?|[A-Za-z]{2,}|[가-힣]{2,}/g;
const particles = ["으로", "에서", "에게", "까지", "부터", "이며", "이고", "하고", "되어", "되며", "하며", "하는", "되는", "한다", "된다", "이다", "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "로", "도", "만", "및"];
const stopWords = new Set("확인 확인한다 있는지 요구 요구된다 요구되며 요구되지만 제공 자료 근거 회사 현재 해당 필요 경우 관련 사업 수행 범위 기준 이상 대한 없는 없이 등 통해 위한".split(" "));

function tokens(text: string): Set<string> {
  const result = new Set<string>();
  for (const raw of text.match(tokenPattern) ?? []) {
    let token = raw.replace(/\s/g, "");
    if (/^[가-힣]/.test(token)) {
      const suffix = particles.find((ending) => token.endsWith(ending) && token.length - ending.length >= 2);
      if (suffix) token = token.slice(0, -suffix.length);
    }
    if (token.length >= 2 && !stopWords.has(token) && !stopWords.has(raw)) result.add(token);
  }
  return result;
}

function sharedScore(left: ReadonlySet<string>, right: ReadonlySet<string>): number {
  let score = 0;
  for (const token of left) {
    if (right.has(token)) score += /^[0-9A-Za-z]/.test(token) ? 3 : 1;
  }
  return score;
}

interface RiskText {
  evidence: { quote: string };
  description: string;
}

export function createEngineRiskLinker(risks: readonly RiskText[]): (text: string) => number | null {
  const candidates = risks.map(({ evidence, description }) => ({
    all: tokens(`${evidence.quote} ${description}`),
    quote: tokens(evidence.quote),
  }));
  return (text) => {
    const input = tokens(text);
    let best: number | null = null;
    let bestScore = 4;
    let bestQuoteScore = -1;
    candidates.forEach(({ all, quote }, index) => {
      const score = sharedScore(input, all);
      const quoteScore = sharedScore(input, quote);
      if (score >= 5 && (score > bestScore || (score === bestScore && quoteScore > bestQuoteScore))) {
        best = index;
        bestScore = score;
        bestQuoteScore = quoteScore;
      }
    });
    return best;
  };
}
