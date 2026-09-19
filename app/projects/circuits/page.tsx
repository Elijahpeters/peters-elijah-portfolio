import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { circuitStudies } from "../../lib/circuit-studies";
import styles from "../engineering.module.css";

export const metadata: Metadata = {
  title: "Circuit studies | Peters Elijah",
  description: "Five circuit studies covering an active inductor, KHN filter, instrumentation amplifier, phase-frequency detector and boost power stage, with their evidence and limitations.",
  alternates: { canonical: "/projects/circuits" },
  openGraph: {
    title: "Circuit studies | Peters Elijah",
    description: "Design goals, annotated schematics and clearly bounded findings across five circuit studies.",
    url: "/projects/circuits",
  },
};

export default function CircuitStudiesPage() {
  return (
    <main className={styles.page}>
      <nav className={styles.nav} aria-label="Circuit studies navigation">
        <Link href="/#circuits">← Back to portfolio</Link>
        <Link href="/projects/incubator-carrier">Explore the KiCad PCB →</Link>
      </nav>
      <header className={styles.hero}>
        <p className={styles.eyebrow}>Circuit laboratory / Five studies</p>
        <h1>The circuit, the reasoning and the evidence.</h1>
        <p>These studies cover analogue signal processing, mixed-signal logic
          and switching power. Each separates the intended behaviour from what
          the available schematic or diagram actually demonstrates.</p>
        <p className={styles.scopeNote}>Design values are not measured results.
          Where plots, simulation files or physical tests are not shown, this
          page does not claim verified performance.</p>
      </header>
      <nav className={styles.jumpLinks} aria-label="Choose a circuit study">
        {circuitStudies.map((study) => <a key={study.id} href={`#${study.id}`}>{study.title}</a>)}
      </nav>
      {circuitStudies.map((study, index) => (
        <section className={styles.section} id={study.id} key={study.id} aria-labelledby={`${study.id}-title`}>
          <p className={styles.eyebrow}>0{index + 1} / {study.type}</p>
          <h2 id={`${study.id}-title`}>{study.title}</h2>
          <p>{study.description}</p>
          <div className={`${styles.split} ${styles.studyContent}`}>
            <div>
              <h3>Purpose</h3><p>{study.purpose}</p>
              <h3>Design approach</h3><p>{study.approach}</p>
            </div>
            <div>
              <h3>Evidence available</h3><p>{study.evidence}</p>
              <h3>What still needs checking</h3><p>{study.nextCheck}</p>
            </div>
          </div>
          <figure className={styles.figure}>
            <a href={study.image} target="_blank" rel="noreferrer" aria-label={`Open the ${study.title} drawing at full size in a new tab`}>
              <Image src={study.image} alt={study.alt} width={study.width} height={study.height} unoptimized />
            </a>
            <figcaption>{study.result}. Select the drawing to open the original image at full size.</figcaption>
          </figure>
          <p className={styles.scopeNote}><strong>Scope and limitations:</strong> {study.limitation}</p>
        </section>
      ))}
      <Link className={styles.action} href="/#contact">Discuss my engineering work →</Link>
    </main>
  );
}
