import { createUser, findUserByEmail, listUsersCreatedAfter } from "../repositories/userRepository";

export async function registerUser(email, name) {
  const existing = await findUserByEmail(email);

  if (existing) {
    throw new Error("User already exists");
  }

  return createUser({ email, name });
}

export async function listRecentUsers(referenceDate) {
  return listUsersCreatedAfter(referenceDate);
}
