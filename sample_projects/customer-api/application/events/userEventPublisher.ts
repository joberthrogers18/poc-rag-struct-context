type UserCreatedEvent = {
  eventName: "user.created";
  userId: number;
  email: string;
  createdAt: string;
  billingStatus: string;
  marketingOptIn: boolean;
};

export async function publishUserCreated(eventBus: { publish: (topic: string, payload: UserCreatedEvent) => Promise<void> }, user: UserCreatedEvent) {
  await eventBus.publish("user.created", {
    eventName: "user.created",
    userId: user.userId,
    email: user.email,
    createdAt: user.createdAt,
    billingStatus: user.billingStatus,
    marketingOptIn: user.marketingOptIn,
  });
}
