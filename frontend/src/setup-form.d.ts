import type { ClinicRoster } from "./organizer-api.js";

export function setupFormErrors(input: {
  date: string;
  clinic: string;
  today: string;
  fullSchedule: boolean;
  roster: ClinicRoster | null;
  rosterKey: string;
  selectionKey: string;
}): Record<string, string>;

export function clinicCodePreview(
  labels: readonly string[],
  value: string,
): { cls: string; html: string };

export const SETUP_FIELDS: readonly string[];

export function hasUnsavedChanges(input: {
  current: {
    hospital?: string;
    date?: string;
    patient_number?: string;
    department_code?: string;
    clinic_code?: string;
    session?: string;
    recipient_ids?: readonly string[];
  };
  saved: {
    hospital: string;
    date: string;
    department_code: string;
    clinic_code: string;
    session: string;
    recipients: readonly { id: string }[];
  } | undefined;
  firstHospital: string;
  firstDepartmentOf: (hospital: string) => string | undefined;
  initialPatientNumber: string | null | undefined;
}): boolean;
