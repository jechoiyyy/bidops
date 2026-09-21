/** Unicode White_Space 16.0 and BOM, matching the backend search contract. */
const SEARCH_SPACES = new Set([
  ...Array.from({ length: 5 }, (_, index) => index + 0x09),
  0x20, 0x85, 0xa0, 0x1680,
  ...Array.from({ length: 11 }, (_, index) => index + 0x2000),
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff,
]);

function isSearchSpace(char: string): boolean {
  return SEARCH_SPACES.has(char.codePointAt(0) ?? -1);
}

export function searchKey(value: string | null | undefined): string {
  if (!value) return "";
  return Array.from(value, (char) => {
    if (isSearchSpace(char)) return "";
    const code = char.codePointAt(0) ?? 0;
    return code >= 0x41 && code <= 0x5a ? String.fromCharCode(code + 32) : char;
  }).join("");
}

export function searchMatches(query: string, ...fields: Array<string | null | undefined>): boolean {
  const needle = searchKey(query);
  return needle !== "" && fields.some((field) => field != null && searchKey(field).includes(needle));
}

export function searchValidationValue(value: string): string {
  let result = "";
  for (const char of value) {
    if (isSearchSpace(char)) {
      if (result && !result.endsWith(" ")) result += " ";
    } else {
      result += char;
    }
  }
  return result.replace(/^ +| +$/g, "");
}

export function opportunitySearchValid(value: string): boolean {
  if (!searchKey(value)) return true;
  const length = Array.from(searchValidationValue(value)).length;
  return length >= 2 && length <= 100;
}
