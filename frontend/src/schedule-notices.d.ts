export function formatMonthDay(isoDate: string): string;

export function formatReleaseTime(isoTimestamp: string | null | undefined): string;

export function notYetPublishedNotice(input: {
  hospitalName: string;
  endDate: string;
  visitDate: string;
  releaseTime: string | null | undefined;
}): string;

export function degradeNotice(reason: string): string;

export function visitErrorMessage(code: string): string;

export function startRefusalMessage(input: {
  code: string;
  details: { schedule_end_date?: string | null; release_time?: string | null } | undefined;
  hospitalName: string;
  visitDate: string;
}): string;
