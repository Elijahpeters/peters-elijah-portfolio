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
  if (
    !risk || risk.status === "unavailable"
  ) {
    return (
      <span className={`${styles.riskBadge} ${styles.riskUnavailable}`}>
        <strong>SkyETA</strong>
        <span>Risk not available for this itinerary</span>
      </span>
    );
  }

  const probability = Math.min(100, Math.max(0, risk.percentage));
  const level = riskClass(risk.level);
  const coverage = risk.coverage === "partial" ? " · partial coverage" : "";

  return (
    <span
      className={`${styles.riskBadge} ${styles[`risk_${level}`]}`}
      aria-label={`SkyETA estimates a ${Math.round(probability)} percent delay risk${coverage}`}
      title={risk.summary}
    >
      <strong>SkyETA</strong>
      <span>
        {Math.round(probability)}% delay risk{coverage}
      </span>
    </span>
  );
}
