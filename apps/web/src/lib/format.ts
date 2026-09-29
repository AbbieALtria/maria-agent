export function localTime(tz: string | null | undefined, at: Date = new Date()): string {
  if (!tz) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: tz,
      hour: "numeric",
      minute: "2-digit",
      weekday: "short",
    }).format(at);
  } catch {
    return "—";
  }
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function label(value: string): string {
  return value.replace(/_/g, " ");
}

export const TIMEZONES: string[] = (() => {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf(
      "timeZone",
    );
  } catch {
    return ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
      "America/Toronto", "America/Vancouver", "Asia/Manila", "UTC"];
  }
})();
