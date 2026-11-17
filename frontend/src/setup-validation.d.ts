import type { ClinicRoster } from "./organizer-api.js";

export function validateSetup(input: {
  date: string;
  today: string;
  clinic: string;
  roster: ClinicRoster | null;
}): Record<string, string>;
