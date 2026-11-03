export const SCHEDULE_LOOKAHEAD_DAYS: number;

export function addDaysISO(iso: string, days: number): string;

export function withinScheduleWindow(
  date: string,
  today: string,
  lookahead?: number,
): boolean;

export function beyondScheduleWindow(
  date: string,
  today: string,
  lookahead?: number,
): boolean;

export function degradeNotice(reason: string): string;

export function visitErrorMessage(code: string): string;
