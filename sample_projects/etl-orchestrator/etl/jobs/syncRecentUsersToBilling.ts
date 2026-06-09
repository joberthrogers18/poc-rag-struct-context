import { findUsersForInvoiceCycle } from "../../../billing-engine/finance/jobs/invoiceEligibilityJob";

export async function syncRecentUsersToBilling(referenceDate, destinationClient) {
  const candidates = await findUsersForInvoiceCycle(referenceDate);

  const payload = candidates.map((candidate) => ({
    userId: candidate.userId,
    email: candidate.email,
    signupDate: candidate.signupDate,
    billingStatus: candidate.billingStatus,
  }));

  await destinationClient.send("billing.invoice-candidates", payload);
  return payload.length;
}
