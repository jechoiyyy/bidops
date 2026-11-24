export function normalizePdfQuote(text: string): string {
  return text.replace(/[\s❍○•·\-–—‧ㆍ]/g, "");
}

export interface PdfTextPage {
  number: number;
  text: string;
}

export type PdfQuoteLocation =
  | { kind: "exact" | "span"; page: number }
  | { kind: "not_found"; page: null };

const notFound: PdfQuoteLocation = { kind: "not_found", page: null };

export function createPdfQuoteLocator(pages: readonly PdfTextPage[]): (quote: string) => PdfQuoteLocation {
  const normalized = [...pages].sort((a, b) => a.number - b.number)
    .map(({ number, text }) => ({ number, text: normalizePdfQuote(text) }));
  const cache = new Map<string, PdfQuoteLocation>();

  function locate(quote: string): PdfQuoteLocation {
    if (quote.length < 4) return notFound;
    for (const page of normalized) {
      if (page.text.includes(quote)) return { kind: "exact", page: page.number };
    }
    for (let index = 0; index < normalized.length - 1; index++) {
      const page = normalized[index];
      const next = normalized[index + 1];
      if (next.number === page.number + 1 && (page.text + next.text).includes(quote)) {
        return { kind: "span", page: page.number };
      }
    }
    return notFound;
  }

  return (rawQuote) => {
    const quote = normalizePdfQuote(rawQuote);
    const cached = cache.get(quote);
    if (cached) return cached;
    const result = locate(quote);
    cache.set(quote, result);
    return result;
  };
}

