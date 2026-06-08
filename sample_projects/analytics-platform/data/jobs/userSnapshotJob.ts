type SourceUser = {
  id: number;
  email: string;
  createdAt: string;
};

type SnapshotRow = {
  userId: number;
  email: string;
  signupDate: string;
  sourceSystem: string;
  snapshotDate: string;
};

export function mapUsersToSnapshot(users: SourceUser[], snapshotDate: string): SnapshotRow[] {
  return users.map((user) => ({
    userId: user.id,
    email: user.email,
    signupDate: user.createdAt,
    sourceSystem: "customer-api",
    snapshotDate,
  }));
}
