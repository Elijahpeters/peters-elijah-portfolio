export class BodyTooLargeError extends Error {
  constructor() {
    super("The JSON body exceeds the allowed size.");
    this.name = "BodyTooLargeError";
  }
}

export class InvalidJsonBodyError extends Error {
  constructor() {
    super("The JSON body is invalid.");
    this.name = "InvalidJsonBodyError";
  }
}

type BodySource = {
  body: ReadableStream<Uint8Array> | null;
  headers: Headers;
};

export async function readBoundedJson(
  source: BodySource,
  maxBytes: number,
): Promise<unknown> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
    throw new TypeError("The JSON byte limit is invalid.");
  }
  const contentLength = Number(source.headers.get("content-length") ?? 0);
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    throw new BodyTooLargeError();
  }
  if (!source.body) throw new InvalidJsonBodyError();

  const reader = source.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      totalBytes += result.value.byteLength;
      if (totalBytes > maxBytes) {
        try {
          await reader.cancel("body_too_large");
        } catch {
          // The size error remains authoritative even if cancellation fails.
        }
        throw new BodyTooLargeError();
      }
      chunks.push(result.value);
    }
  } catch (error) {
    if (error instanceof BodyTooLargeError) throw error;
    throw new InvalidJsonBodyError();
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new InvalidJsonBodyError();
  }
}
