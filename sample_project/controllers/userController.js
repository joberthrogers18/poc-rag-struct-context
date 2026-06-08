const userService = require('../services/userService');

async function register(req, res) {
  try {
    const { email, name } = req.body;
    const user = await userService.registerUser(email, name);
    res.status(201).json(user);
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
}

module.exports = { register };