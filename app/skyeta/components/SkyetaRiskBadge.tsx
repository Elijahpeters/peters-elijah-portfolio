import type { SkyetaRiskAssessment } from "./flight-ui-types";
import styles from "../booking.module.css";

export interface SkyetaRiskBadgeProps {
  risk?: SkyetaRiskAssessment;
}

function riskClass(level: "lower" | "moderate" | "higher") {
  if (level === "lower") return "low";
  if (level === "higher") return "elevated";
  return "moderate";
}

export default function SkyetaRiskBadge({ risk }: SkyetaRiskBadgeProps) {
  if (!risk || risk.status === "unavailable") {
    const explanation =
      "SkyETA does not yet have verified delay coverage for this route.";

    return (
      <span
        className={`${styles.riskBadge} ${styles.riskUnavailable}`}
        aria-label="Journey insight: delay outlook not yet verified for this route"
        title={explanation}
      >
        <strong>Journey insight</strong>
        <span>Delay outlook not yet verified for this route</span>
      </span>
    );
  }

  if (risk.coverage === "partial") {
    const coverage = `${risk.scoredSegments} of ${risk.totalSegments} flight segments analysed`;
    const explanation = `SkyETA analysed ${risk.scoredSegments} of ${risk.totalSegments} flight segments. A whole-journey delay percentage is not shown.`;

    return (
      <span
        className={`${styles.riskBadge} ${styles.riskUnavailable}`}
        aria-label={`Journey insight: ${coverage}. A whole-journey delay percentage is not shown.`}
        title={explanation}
      >
        <strong>Journey insight</strong>
        <span>{coverage}</span>
      </span>
    );
  }

  const probability = Math.min(100, Math.max(0, risk.percentage));
  const level = riskClass(risk.level);
  const roundedProbability = Math.round(probability);
  const explanation = `Late-arrival outlook: ${roundedProbability}% chance of arriving 15+ minutes late; about ${roundedProbability} in 100 similar flights.`;

  return (
    <span
      className={`${styles.riskBadge} ${styles[`risk_${level}`]}`}
      aria-label={explanation}
      title={explanation}
    >
      <strong>Late-arrival outlook</strong>
      <span>{roundedProbability}% chance of arriving 15+ minutes late</span>
    </span>
  );
}
