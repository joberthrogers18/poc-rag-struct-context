type InvoiceCandidate = {
  userId: number;
  billingStatus: string;
  signupDate: string;
};

type RevenueWindow = {
  userId: number;
  recognitionMonth: string;
  sourceReference: string;
};

export function buildRevenueWindows(candidates: InvoiceCandidate[]): RevenueWindow[] {
  return candidates
    .filter((candidate) => candidate.billingStatus !== "cancelled")
    .map((candidate) => ({
      userId: candidate.userId,
      recognitionMonth: candidate.signupDate.slice(0, 7),
      sourceReference: "billing-engine.invoice_eligibility.signupDate",
    }));
}
