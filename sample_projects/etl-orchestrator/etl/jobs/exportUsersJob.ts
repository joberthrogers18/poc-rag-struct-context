const userRepository = require("../../../customer-api/application/repositories/userRepository");

async function exportRecentUsers(createdAfter, destinationClient) {
  const users = await userRepository.listUsersCreatedAfter(createdAfter);

  const payload = users.map((user) => ({
    userId: user.id,
    email: user.email,
    createdAt: user.createdAt,
  }));

  await destinationClient.send("users.recent", payload);
  return payload.length;
}

module.exports = {
  exportRecentUsers,
};
