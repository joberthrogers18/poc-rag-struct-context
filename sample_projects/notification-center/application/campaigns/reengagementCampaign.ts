import { collectRecentUsersForCampaign } from "../../../customer-api/application/services/userLifecycleService";

export async function buildReengagementAudience(createdAfter) {
  const users = await collectRecentUsersForCampaign(createdAfter);

  return users.map((user) => ({
    userId: user.id,
    email: user.email,
    firstSeenAt: user.createdAt,
    marketingOptIn: user.marketingOptIn,
  }));
}
