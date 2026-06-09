import { listRecentUsers, registerUser } from "../services/userService";

export async function postUser(req, res) {
  const user = await registerUser(req.body.email, req.body.name);
  res.status(201).json(user);
}

export async function getRecentUsers(req, res) {
  const date = new Date(req.query.createdAfter);
  const users = await listRecentUsers(date);
  res.json(users);
}
