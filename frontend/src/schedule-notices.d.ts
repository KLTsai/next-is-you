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
