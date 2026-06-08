const userService = require("../services/userService");

async function postUser(req, res) {
  const user = await userService.registerUser(req.body.email, req.body.name);
  res.status(201).json(user);
}

async function getRecentUsers(req, res) {
  const date = new Date(req.query.createdAfter);
  const users = await userService.listRecentUsers(date);
  res.json(users);
}

module.exports = {
  postUser,
  getRecentUsers,
};
