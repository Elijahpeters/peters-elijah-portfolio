export type FlightDateParts = {
  time: string;
  date: string;
};

export function flightDateParts(
  value: string,
  timeZone?: string | null,
  locale?: string | string[],
): FlightDateParts {
  const offsetless = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(
    value,
  );
  const parsed = offsetless
    ? new Date(
        Date.UTC(
          Number(offsetless[1]),
          Number(offsetless[2]) - 1,
          Number(offsetless[3]),
          Number(offsetless[4]),
          Number(offsetless[5]),
          Number(offsetless[6] ?? 0),
        ),
      )
    : new Date(value);
  const displayTimeZone = offsetless ? "UTC" : timeZone || undefined;
  if (Number.isNaN(parsed.getTime())) return { time: value, date: "" };
  try {
    return {
      time: new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: displayTimeZone,
      }).format(parsed),
      date: new Intl.DateTimeFormat(locale, {
        weekday: "short",
        month: "short",
        day: "numeric",
        timeZone: displayTimeZone,
      }).format(parsed),
    };
  } catch {
    return { time: value, date: "" };
  }
}
