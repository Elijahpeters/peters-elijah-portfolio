import type {
  BaggageAllowance,
  FareConditions as FareConditionsData,
  FareRule,
  Money,
} from "../../types/flight-booking";
import styles from "../booking.module.css";

export interface FareConditionsProps {
  conditions?: FareConditionsData;
  baggage?: BaggageAllowance[];
  cabinName?: string | null;
  fareBrandName?: string | null;
}

function formatMoney(money?: Money) {
  if (!money) return null;
  const value = Number(money.amount);
  if (!Number.isFinite(value)) return `${money.currency} ${money.amount}`;

  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: money.currency,
    }).format(value);
  } catch {
    return `${money.currency} ${money.amount}`;
  }
}

function policyLabel(rule: FareRule, positive: string, negative: string) {
  if (rule.status === "unknown") return "Check airline conditions";
  return rule.status === "allowed" ? positive : negative;
}

export default function FareConditions({
  conditions,
  baggage,
  cabinName,
  fareBrandName,
}: FareConditionsProps) {
  if (!conditions) {
    return (
      <p className={styles.conditionsUnavailable}>
        Fare conditions will be shown when the provider supplies them.
      </p>
    );
  }

  const distinctBaggage = Array.from(
    new Map(
      (baggage || []).map((item) => [
        `${item.type}:${item.providerType}:${item.quantity}:${item.weightKilograms}`,
        item,
      ]),
    ).values(),
  );

  return (
    <details className={styles.fareConditions}>
      <summary>Fare, baggage and change conditions</summary>
      <div className={styles.conditionsBody}>
        <dl className={styles.conditionsGrid}>
          <div>
            <dt>Fare</dt>
            <dd>
              {[cabinName, fareBrandName]
                .filter(Boolean)
                .join(" · ") || "Standard fare"}
            </dd>
          </div>
          <div>
            <dt>Changes</dt>
            <dd>
              {policyLabel(
                conditions.changeBeforeDeparture,
                "Changes permitted",
                "Changes not permitted",
              )}
              {conditions.changeBeforeDeparture.penalty
                ? ` · fee up to ${formatMoney(conditions.changeBeforeDeparture.penalty)}`
                : ""}
            </dd>
          </div>
          <div>
            <dt>Refunds</dt>
            <dd>
              {policyLabel(
                conditions.refundBeforeDeparture,
                "Refundable",
                "Non-refundable",
              )}
              {conditions.refundBeforeDeparture.penalty
                ? ` · fee up to ${formatMoney(conditions.refundBeforeDeparture.penalty)}`
                : ""}
            </dd>
          </div>
        </dl>

        <div className={styles.baggageBlock}>
          <h4>Baggage included</h4>
          {distinctBaggage.length ? (
            <ul>
              {distinctBaggage.map((item, index) => (
                <li key={`${item.segmentId}-${item.type}-${index}`}>
                  <strong>{item.type.replace("_", " ")}</strong>
                  <span>
                    {item.quantity !== null
                      ? `${item.quantity} piece${item.quantity === 1 ? "" : "s"}`
                      : item.weightKilograms !== null
                        ? `${item.weightKilograms} kg`
                        : "Allowance supplied"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No baggage allowance was supplied for this fare.</p>
          )}
        </div>

      </div>
    </details>
  );
}
