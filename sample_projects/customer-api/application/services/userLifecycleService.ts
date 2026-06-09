import {
  listMarketingOptInUsersCreatedAfter,
  listUsersEligibleForBilling,
} from "../repositories/userRepository";

export async function collectRecentUsersForCampaign(createdAfter) {
  return listMarketingOptInUsersCreatedAfter(createdAfter);
}

export async function collectUsersForBilling(referenceDate) {
  return listUsersEligibleForBilling(referenceDate);
}
