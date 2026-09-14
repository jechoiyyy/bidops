const HEX = Array.from({ length: 256 }, (_, value) => value.toString(16).padStart(2, "0"));

/**
 * Generate an RFC 4122 version 4 UUID from the Web Crypto random source.
 *
 * `crypto.getRandomValues()` is available on HTTP origins. Do not add a
 * non-cryptographic fallback here:
 * callers must fail closed when secure randomness is unavailable.
 */
export function generateRequestId(): string {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi || typeof cryptoApi.getRandomValues !== "function") {
    throw new Error("Web Crypto secure randomness is unavailable");
  }

  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  return [
    HEX[bytes[0]] + HEX[bytes[1]] + HEX[bytes[2]] + HEX[bytes[3]],
    HEX[bytes[4]] + HEX[bytes[5]],
    HEX[bytes[6]] + HEX[bytes[7]],
    HEX[bytes[8]] + HEX[bytes[9]],
    HEX[bytes[10]] + HEX[bytes[11]] + HEX[bytes[12]] + HEX[bytes[13]] + HEX[bytes[14]] + HEX[bytes[15]],
  ].join("-");
}
