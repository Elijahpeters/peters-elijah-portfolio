import type { Metadata } from "next";
import Link from "next/link";
import styles from "./case-study.module.css";
import ProjectBrief from "../../components/ProjectBrief";
import { projectBriefs } from "../../lib/project-briefs";

export const metadata: Metadata = {
  title: "SkyETA | Flight Intelligence Case Study by Elijah Peters",
  description: "Flight-data analysis, delay modelling and fare-search integration by Elijah Peters, with model validation, coverage limits and engineering evidence.",
  alternates: { canonical: "/projects/skyeta" },
  openGraph: {
    type: "website",
    siteName: "Elijah Peters | Engineering Portfolio",
    url: "/projects/skyeta",
    title: "SkyETA | Flight Intelligence Case Study by Elijah Peters",
    description: "Flight-data analysis, delay modelling and fare-search integration by Elijah Peters, with model validation, coverage limits and engineering evidence.",
    images: [{ url: "/skyeta/opengraph-image", width: 1200, height: 630, alt: "SkyETA by Elijah Peters (Peters Elijah Temidayo)" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SkyETA | Flight Intelligence Case Study by Elijah Peters",
    description: "Flight-data analysis, delay modelling and fare-search integration by Elijah Peters, with model validation, coverage limits and engineering evidence.",
    images: [{ url: "/skyeta/opengraph-image", alt: "SkyETA by Elijah Peters (Peters Elijah Temidayo)" }],
  },
};

export default function SkyetaCaseStudy() {
  return (
    <main className={`case-study-page ${styles.page}`}>
      <nav className="case-study-nav" aria-label="Case study navigation">
        <Link href="/#projects">← Back to portfolio</Link>
        <Link href="/skyeta">Open SkyETA ↗</Link>
      </nav>
      <header className="case-study-hero">
        <p className="section-label">SkyETA / Engineering case study</p>
        <h1>Flight data, predictive modelling and fare search.</h1>
        <p>A flight-intelligence application combining provider-backed search with historical flight analysis. Model estimates and observed records remain separate, with coverage limits stated beside the results.</p>
      </header>
        <article className="skyeta-project" id="skyeta">
          <div className="skyeta-copy">
            <p className="project-type">Machine learning · Systems engineering</p>
            <h2>SkyETA</h2>
            <p className="skyeta-lead">
              A flight-intelligence workspace for comparing provider-backed
              fares worldwide and understanding the evidence available for a
              journey.
            </p>
            <p>
              SkyETA brings fare, schedule and operational sources into one
              organised view. It checks route-matched 15+, 30+ and 60+ minute
              delay history worldwide when records exist, while its trained
              schedule model remains limited to verified U.S. routes.
            </p>

            <div className="skyeta-workflow" aria-labelledby="skyeta-workflow-title">
              <p id="skyeta-workflow-title">How SkyETA works</p>
              <ol>
                <li>
                  <span>01</span>
                  <strong>Search the journey</strong>
                  <small>Choose a route, date, cabin and passenger count.</small>
                </li>
                <li>
                  <span>02</span>
                  <strong>Compare real options</strong>
                  <small>Review current fares, schedules, stops and baggage.</small>
                </li>
                <li>
                  <span>03</span>
                  <strong>Understand the evidence</strong>
                  <small>See flight-specific history, sample confidence and U.S. model coverage.</small>
                </li>
              </ol>
              <small>
                SkyETA labels provider fares, observed AirLabs information and
                historical model estimates separately so visitors know what each
                result means.
              </small>
            </div>

            <dl className="project-details">
              <div>
                <dt>Role</dt>
                <dd>Systems engineering, machine learning &amp; instrumentation UI</dd>
              </div>
              <div>
                <dt>Stack</dt>
                <dd>Python, machine learning, Pandas &amp; TypeScript</dd>
              </div>
              <div>
                <dt>Evidence</dt>
                <dd>5.15M U.S. records profiled · 750k model-fit sample · 643k Brazilian schedules matched to outcomes</dd>
              </div>
            </dl>

            <div className="project-actions">
              <a
                className="project-action"
                href="/skyeta"
                target="_blank"
                rel="noreferrer"
                aria-label="Open SkyETA in a new tab"
              >
                Open SkyETA <span aria-hidden="true">↗</span>
              </a>
              <a
                className="project-action"
                href="https://github.com/Elijahpeters/peters-elijah-portfolio"
                target="_blank"
                rel="noreferrer"
                aria-label="View the integrated SkyETA source on GitHub in a new tab"
              >
                View SkyETA source <span aria-hidden="true">↗</span>
              </a>
              <a
                className="project-action"
                href="https://github.com/Elijahpeters/peters-elijah-portfolio/blob/main/skyeta-ml/global/ANAC_2023_ANNUAL_MODEL_GATE_REVIEW.md"
                target="_blank"
                rel="noreferrer"
                aria-label="Read the SkyETA annual model gate review on GitHub in a new tab"
              >
                Read model audit <span aria-hidden="true">↗</span>
              </a>
            </div>
          </div>

          <aside className="skyeta-portfolio-preview" aria-label="SkyETA information layers">
            <p className="project-type">What each result separates</p>
            <h3>One journey, three clearly labelled evidence layers.</h3>
            <dl>
              <div>
                <dt>01 / Fare</dt>
                <dd>Current provider price, schedule, stops and baggage.</dd>
              </div>
              <div>
                <dt>02 / Delay outlook</dt>
                <dd>A plain-language percentage only where model coverage is verified.</dd>
              </div>
              <div>
                <dt>03 / Recent history</dt>
                <dd>Route-matched completed-flight evidence when available.</dd>
              </div>
            </dl>
            <a className="project-action" href="/skyeta" target="_blank" rel="noreferrer">
              Explore SkyETA <span aria-hidden="true">↗</span>
            </a>
          </aside>
        </article>

        <ProjectBrief brief={projectBriefs.skyeta} />

      <nav className="case-study-nav" aria-label="Further project evidence">
        <a href="/assets/skyeta-model-card.json">Read the model card →</a>
        <Link href="/#projects">Back to featured projects →</Link>
      </nav>
    </main>
  );
}
