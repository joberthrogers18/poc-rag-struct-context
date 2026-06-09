type UserCreatedPayload = {
  userId: number;
  email: string;
  createdAt: string;
  marketingOptIn: boolean;
};

export function buildWelcomeJourneyMessages(events: UserCreatedPayload[]) {
  return events
    .filter((event) => event.marketingOptIn)
    .map((event) => ({
      channel: "email",
      template: "welcome-journey",
      recipient: event.email,
      scheduledAt: event.createdAt,
      sourceReference: "customer-api.user.createdAt",
    }));
}
