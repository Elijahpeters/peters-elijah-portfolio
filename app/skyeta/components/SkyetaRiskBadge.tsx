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
      "The U.S. schedule model covers selected U.S. domestic routes only. Worldwide flight history is checked separately below.";

    return (
      <span
        className={`${styles.riskBadge} ${styles.riskUnavailable}`}
        aria-label="U.S. schedule model unavailable for this route; worldwide flight history is checked separately"
        title={explanation}
      >
        <strong>U.S. schedule model</strong>
        <span>Not available outside selected U.S. routes</span>
      </span>
    );
  }

  if (risk.scope === "highest_scored_segment") {
    const coverage = `${risk.scoredSegments} of ${risk.totalSegments} flight segments analysed`;
    const explanation = `The U.S. schedule model analysed ${risk.scoredSegments} of ${risk.totalSegments} flight segments separately. A whole-journey delay percentage is not shown.`;

    return (
      <span
        className={`${styles.riskBadge} ${styles.riskUnavailable}`}
        aria-label={`U.S. schedule model: ${coverage}. A whole-journey delay percentage is not shown.`}
        title={explanation}
      >
        <strong>U.S. schedule model</strong>
        <span>{coverage}</span>
      </span>
    );
  }

  const probability = Math.min(100, Math.max(0, risk.percentage));
  const level = riskClass(risk.level);
  const roundedProbability = Math.round(probability);
  const explanation = `U.S. schedule-model outlook: ${roundedProbability}% chance that this flight segment arrives 15+ minutes late; about ${roundedProbability} in 100 comparable flights.`;

  return (
    <span
      className={`${styles.riskBadge} ${styles[`risk_${level}`]}`}
      aria-label={explanation}
      title={explanation}
    >
      <strong>U.S. schedule model</strong>
      <span>{roundedProbability}% chance this flight arrives 15+ minutes late</span>
    </span>
  );
}
