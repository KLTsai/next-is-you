import type { OrganizerVisit } from "./organizer-api.js";

export const VISIT_STATES: readonly OrganizerVisit["state"][];
export const SOURCE_STATUSES: readonly OrganizerVisit["source_read"]["status"][];
export function formatVisitState(state: string): string;
export function formatSourceStatus(status: string): string;
export function visitStatusKey(visit: OrganizerVisit): string;
export function canRequestStart(visit: OrganizerVisit | null): boolean;
