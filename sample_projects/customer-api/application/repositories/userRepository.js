const prisma = require("../prisma/client");

async function findUserByEmail(email) {
  return prisma.user.findUnique({
    where: { email },
    select: {
      id: true,
      email: true,
      name: true,
      createdAt: true,
      status: true,
    },
  });
}

async function createUser(data) {
  return prisma.user.create({
    data: {
      email: data.email,
      name: data.name,
      status: "active",
    },
  });
}

async function listUsersCreatedAfter(date) {
  return prisma.user.findMany({
    where: {
      createdAt: {
        gte: date,
      },
    },
    orderBy: {
      createdAt: "desc",
    },
  });
}

module.exports = {
  findUserByEmail,
  createUser,
  listUsersCreatedAfter,
};
