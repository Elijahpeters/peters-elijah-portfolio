export function isoDurationMinutes(value: string | null): number | null {
  if (!value) return null;
  const match = value.match(
    /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:\d+(?:\.\d+)?S)?)?$/,
  );
  if (!match) return null;
  const minutes =
    Number(match[1] ?? 0) * 1_440 +
    Number(match[2] ?? 0) * 60 +
    Number(match[3] ?? 0);
  return minutes > 0 ? minutes : null;
}
