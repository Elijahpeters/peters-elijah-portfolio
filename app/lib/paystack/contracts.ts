export type PaystackEnvironment = "test" | "live";

export type PaystackChannel =
  | "card"
  | "bank"
  | "apple_pay"
  | "ussd"
  | "qr"
  | "mobile_money"
  | "bank_transfer"
  | "eft"
  | "capitec_pay"
  | "payattitude";

export type PaystackInitializeTransactionInput = {
  email: string;
  /** Amount in the currency's smallest subunit. */
  amount: number | string;
  currency?: string;
  reference?: string;
  callbackUrl?: string;
  metadata?: string | Readonly<Record<string, unknown>>;
  channels?: readonly PaystackChannel[];
};

export type PaystackInitializeTransactionResult = {
  authorizationUrl: string;
  accessCode: string;
  reference: string;
  environment: PaystackEnvironment;
  requestId: string | null;
};

export type PaystackVerifyTransactionResult = {
  status: string;
  reference: string;
  amount: number;
  currency: string;
  environment: PaystackEnvironment;
  paidAt: string | null;
  channel: string | null;
  customerEmail: string | null;
  /** Only the reconciliation identifier is retained from provider metadata. */
  metadata: { bookingAttemptId: string } | null;
  requestId: string | null;
};

export type PaystackApiEnvelope = {
  status?: unknown;
  message?: unknown;
  data?: unknown;
};
