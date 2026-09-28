export type VisitStatus = "draft" | "active" | "stopping" | "stopped" | "source-unavailable" | "terminal";
export interface ExpectedVisit {
  hospital: string;
  visitDate: string;
  departmentCode: string | null;
  clinicCode: string | null;
  session: string | null;
}
export interface Observation extends ExpectedVisit {
  trustworthy: boolean;
  observedAt: string;
  currentNumber: number | null;
  nextNumber: number | null;
  callType: string | null;
}
export function formatStatus(status: VisitStatus): string;
export function isFreshMatchingObservation(observation: Observation | null, expected: ExpectedVisit, now?: number): boolean;
export function canStartVisit(visit: ExpectedVisit & { status: VisitStatus; recipients: string[]; observation: Observation | null }, now?: number): boolean;
