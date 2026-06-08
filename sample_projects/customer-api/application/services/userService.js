const userRepository = require("../repositories/userRepository");

async function registerUser(email, name) {
  const existing = await userRepository.findUserByEmail(email);

  if (existing) {
    throw new Error("User already exists");
  }

  return userRepository.createUser({ email, name });
}

async function listRecentUsers(referenceDate) {
  return userRepository.listUsersCreatedAfter(referenceDate);
}

module.exports = {
  registerUser,
  listRecentUsers,
};
