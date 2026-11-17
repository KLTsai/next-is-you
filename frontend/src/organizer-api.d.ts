export type Hospital = "ntuh-main" | "shin-kong-taipei";
export type Session = "morning" | "afternoon" | "evening";
export type SourceCapability = "full_schedule" | "current_number_only" | "unsupported";
export type VisitState = "draft" | "active" | "stopping" | "stopped" | "expired";

export interface SupportedDepartment {
  code: string;
  display_name: string;
}

export interface HospitalCatalogEntry {
  hospital: Hospital;
  display_name: string;
  capability: SourceCapability;
  source_url: string | null;
  clinic_code_labels: string[];
  departments: SupportedDepartment[];
}

export interface ClinicOption {
  session: Session;
  room: string;
  doctor: string;
  clinic_type: string;
  clinic_code: string;
}

export interface ClinicRoster {
  available: boolean;
  reason: string;
  clinics: ClinicOption[];
  // Present when the day is not yet published: the last day the hospital's
  // clinic schedule covers, and when the hospital says the day will be added.
  schedule_end?: string | null;
  release_time?: string | null;
}
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
  patient_number?: number;
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
export function listHospitals(options?: object): Promise<{ hospitals: HospitalCatalogEntry[] }>;
export function listClinics(hospital: string, department: string, date: string, options?: object): Promise<ClinicRoster>;
export function getVisitCorrection(id: string, options?: object): Promise<{ patient_number: number }>;
export function createVisit(input: VisitInput, options?: object): Promise<{ id: string; state: "draft" }>;
export function updateVisit(id: string, input: VisitInput, options?: object): Promise<{ id: string; state: "draft" }>;
export function startVisit(id: string, options?: object): Promise<{ state: "active" }>;
export function stopVisit(id: string, options?: object): Promise<{ state: "stopping" | "stopped" }>;
export function removeVisitRecipient(visitId: string, recipientId: string, options?: object): Promise<null>;
export function correctVisit(id: string, input: VisitInput, options?: object): Promise<{ id: string; state: "draft" }>;
export function createInvitation(memberLabel: string, options?: object): Promise<{ invitation_url: string; expires_at: string }>;
export function withdrawMember(recipientId: string, options?: object): Promise<null>;
