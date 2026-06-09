import prisma from "../prisma/client";

export async function findUserByEmail(email) {
  return prisma.user.findUnique({
    where: { email },
    select: {
      id: true,
      email: true,
      name: true,
      createdAt: true,
      status: true,
      billingStatus: true,
      marketingOptIn: true,
    },
  });
}

export async function createUser(data) {
  return prisma.user.create({
    data: {
      email: data.email,
      name: data.name,
      status: "active",
    },
  });
}

export async function listUsersCreatedAfter(date) {
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

export async function listUsersEligibleForBilling(referenceDate) {
  return prisma.user.findMany({
    where: {
      createdAt: {
        lte: referenceDate,
      },
      billingStatus: {
        in: ["trial", "overdue"],
      },
    },
    select: {
      id: true,
      email: true,
      createdAt: true,
      billingStatus: true,
    },
  });
}

export async function listMarketingOptInUsersCreatedAfter(date) {
  return prisma.user.findMany({
    where: {
      createdAt: {
        gte: date,
      },
      marketingOptIn: true,
    },
    select: {
      id: true,
      email: true,
      name: true,
      createdAt: true,
      marketingOptIn: true,
    },
  });
}
