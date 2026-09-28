export type Hospital = "ntuh-main" | "shin-kong-taipei";
export type VisitState = "draft" | "active" | "stopping" | "stopped" | "expired";
export type SourceReadStatus = "usable" | "unavailable" | "stale" | "untrusted" | "scope_mismatch" | "invalid";
export type SourceReadReason = "none" | "no_observation" | "timeout" | "stale_sample" | "untrusted_source" | "scope_mismatch" | "empty_result" | "schema_drift" | "access_denied" | "ambiguous_match" | "invalid_data";

export interface Recipient {
  id: string;
  display_name: string;
}

export interface OrganizerVisit {
  id: string;
  hospital: Hospital;
  date: string;
  department_code: string;
  clinic_code: string;
  session: "morning" | "afternoon" | "evening";
  state: VisitState;
  observation: { current_number: number | null; checked_at: string | null };
  source_read: { status: SourceReadStatus; reason: SourceReadReason };
  notification: { count: number; accepted: number; issues: number };
  recipients: Recipient[];
  source_url?: string;
}

export interface VisitInput {
  hospital: Hospital;
  date: string;
  department_code: string;
  clinic_code: string;
  session: OrganizerVisit["session"];
  patient_number: number;
  recipient_ids: string[];
}

export class OrganizerApiError extends Error {
  status: number;
  code: string;
}

export function listRecipients(options?: object): Promise<{ recipients: Recipient[] }>;
export function listVisits(options?: object): Promise<{ visits: OrganizerVisit[] }>;
export function createVisit(input: VisitInput, options?: object): Promise<{ id: string; state: "draft" }>;
export function updateVisit(id: string, input: VisitInput, options?: object): Promise<{ id: string; state: "draft" }>;
export function startVisit(id: string, options?: object): Promise<{ state: "active" }>;
export function stopVisit(id: string, options?: object): Promise<{ state: "stopping" | "stopped" }>;
export function correctVisit(id: string, input: VisitInput, options?: object): Promise<{ id: string; state: "draft" }>;
