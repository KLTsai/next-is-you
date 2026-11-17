import type { ClinicRoster } from "./organizer-api.js";

export function unpublishedDayNotice(input: {
  hospitalName: string;
  scheduleEnd: string;
  releaseTime: string | null | undefined;
  visitDate: string;
}): string;

export function rosterClinicError(
  roster: ClinicRoster | null,
  clinic: string,
  isToday: boolean,
): string;

export function degradeNotice(reason: string): string;

export function visitErrorMessage(code: string): string;

export function startRefusalMessage(input: {
  code: string;
  hospitalName?: string;
  scheduleEnd?: string | null;
  releaseTime?: string | null;
  visitDate?: string;
}): string;
