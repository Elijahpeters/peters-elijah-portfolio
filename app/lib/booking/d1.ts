import {
  BOOKING_SCHEMA_OPTIMIZE_STATEMENT,
  BOOKING_SCHEMA_STATEMENTS,
} from "../../../db/schema.ts";

export type D1ResultLike<T = unknown> = {
  success: boolean;
  results?: T[];
  error?: string;
  meta?: {
    changes?: number;
    last_row_id?: number;
  };
};

export interface D1PreparedStatementLike {
  bind(...values: unknown[]): D1PreparedStatementLike;
  first<T = Record<string, unknown>>(columnName?: string): Promise<T | null>;
  run<T = unknown>(): Promise<D1ResultLike<T>>;
  all<T = unknown>(): Promise<D1ResultLike<T>>;
}

export interface D1DatabaseLike {
  prepare(sql: string): D1PreparedStatementLike;
  batch<T = unknown>(
    statements: D1PreparedStatementLike[],
  ): Promise<D1ResultLike<T>[]>;
}

const initializationByBinding = new WeakMap<object, Promise<void>>();

export function isD1DatabaseLike(value: unknown): value is D1DatabaseLike {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<D1DatabaseLike>;
  return (
    typeof candidate.prepare === "function" &&
    typeof candidate.batch === "function"
  );
}

/**
 * Creates missing tables/indexes for local and newly provisioned D1 databases.
 * Production deployments should still apply the checked-in migration.
 */
export async function initializeBookingStorage(
  db: D1DatabaseLike,
): Promise<void> {
  const bindingKey = db as object;
  const existing = initializationByBinding.get(bindingKey);
  if (existing) return existing;

  const initialization = (async () => {
    const results = await db.batch(
      BOOKING_SCHEMA_STATEMENTS.map((statement) => db.prepare(statement)),
    );
    const failed = results.find((result) => result.success === false);
    if (failed) {
      throw new Error(failed.error ?? "D1 booking schema initialization failed.");
    }

    const optimization = await db
      .prepare(BOOKING_SCHEMA_OPTIMIZE_STATEMENT)
      .run();
    if (optimization.success === false) {
      throw new Error(optimization.error ?? "D1 query planner optimization failed.");
    }
  })();

  initializationByBinding.set(bindingKey, initialization);
  try {
    await initialization;
  } catch (error) {
    initializationByBinding.delete(bindingKey);
    throw error;
  }
}

export function d1Changes(result: D1ResultLike): number {
  return result.meta?.changes ?? 0;
}
