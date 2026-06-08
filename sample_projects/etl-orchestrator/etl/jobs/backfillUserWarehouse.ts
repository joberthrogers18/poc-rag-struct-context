type ApiUser = {
  id: number;
  email: string;
  createdAt: string;
};

type WarehouseRow = {
  userId: number;
  email: string;
  signupDate: string;
  importedAt: string;
};

export function buildWarehouseBackfill(users: ApiUser[], importedAt: string): WarehouseRow[] {
  return users.map((user) => ({
    userId: user.id,
    email: user.email,
    signupDate: user.createdAt,
    importedAt,
  }));
}
