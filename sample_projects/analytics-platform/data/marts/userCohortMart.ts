type UserSnapshot = {
  userId: number;
  signupDate: string;
  sourceSystem: string;
};

type CohortMetric = {
  cohortMonth: string;
  totalUsers: number;
  sourceReference: string;
};

export function buildUserCohortMetrics(rows: UserSnapshot[]): CohortMetric[] {
  const grouped = new Map<string, number>();

  for (const row of rows) {
    const cohortMonth = row.signupDate.slice(0, 7);
    grouped.set(cohortMonth, (grouped.get(cohortMonth) || 0) + 1);
  }

  return Array.from(grouped.entries()).map(([cohortMonth, totalUsers]) => ({
    cohortMonth,
    totalUsers,
    sourceReference: "analytics-platform.user_snapshot.signupDate",
  }));
}
