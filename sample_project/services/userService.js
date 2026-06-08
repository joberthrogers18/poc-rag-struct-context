const userRepo = require('../repositories/userRepository');

async function registerUser(email, name) {
  const existing = await userRepo.findUserByEmail(email);
  if (existing) {
    throw new Error('User already exists');
  }
  return await userRepo.createUser({ email, name });
}

module.exports = { registerUser };