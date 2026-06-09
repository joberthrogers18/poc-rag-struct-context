import { listUsersCreatedAfter } from "../../../customer-api/application/repositories/userRepository";

export async function exportRecentUsers(createdAfter, destinationClient) {
  const users = await listUsersCreatedAfter(createdAfter);

  const payload = users.map((user) => ({
    userId: user.id,
    email: user.email,
    createdAt: user.createdAt,
  }));

  await destinationClient.send("users.recent", payload);
  return payload.length;
}
