const { PrismaClient } = require("@prisma/client");
const prisma = new PrismaClient();

async function findUserByEmail(email) {
  return await prisma.user.findUnique({
    where: { email },
  });
}

async function createUser(data) {
  return await prisma.user.create({
    data,
  });
}

module.exports = { findUserByEmail, createUser };
