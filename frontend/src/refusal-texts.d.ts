export interface RefusalFacts {
  hospitalName?: string;
  scheduleEnd?: string | null;
  releaseTime?: string | null;
  visitDate?: string | null;
}

export interface RefusalText {
  text: string | ((facts?: RefusalFacts) => string);
  action: string;
}

export const REFUSAL_TEXTS: Readonly<Record<string, RefusalText>>;

export function visitErrorMessage(code: string, facts?: RefusalFacts): string;

export function startRefusalMessage(input: { code: string } & RefusalFacts): string;
