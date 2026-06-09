import { collectUsersForBilling } from "../../../customer-api/application/services/userLifecycleService";

export async function findUsersForInvoiceCycle(referenceDate) {
  const users = await collectUsersForBilling(referenceDate);

  return users.map((user) => ({
    userId: user.id,
    email: user.email,
    billingStatus: user.billingStatus,
    signupDate: user.createdAt,
  }));
}
