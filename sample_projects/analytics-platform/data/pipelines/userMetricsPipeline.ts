type UserRecord = {
  id: number;
  email: string;
  createdAt: string;
  status: string;
};

type DailyMetric = {
  metricDate: string;
  newUsersCount: number;
  activeUsers: number;
  sourceReference: string;
};

export function buildDailyUserMetrics(users: UserRecord[], metricDate: string): DailyMetric {
  const newUsersCount = users.filter((user) => user.createdAt.startsWith(metricDate)).length;
  const activeUsers = users.filter((user) => user.status === "active").length;

  return {
    metricDate,
    newUsersCount,
    activeUsers,
    sourceReference: "customer-api.user.createdAt",
  };
}
