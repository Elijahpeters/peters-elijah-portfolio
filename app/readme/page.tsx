import type { Metadata } from "next";
import Link from "next/link";
import readme from "../../README.md?raw";
import ReadmeContent from "./ReadmeContent";
import styles from "./readme.module.css";

const title = "Portfolio README | Engineering & Applied AI by Elijah Peters";
const description = "The problems, engineering decisions, findings, next steps and limitations behind SkyETA, AuraPass, PCB design and circuit studies by Elijah Peters.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: "/readme" },
  openGraph: {
    type: "website", url: "/readme", title, description,
    images: [{ url: "/og-2026-introduction.jpg", width: 1200, height: 630, alt: "Elijah Peters — Peters Elijah Temidayo, Electrical & Electronics Engineer" }],
  },
  twitter: { card: "summary_large_image", title, description, images: ["/og-2026-introduction.jpg"] },
};

export default function PortfolioReadme() {
  const [projects, repositoryNotes = ""] = readme.split("\n## About this repository\n");
  return (
    <main className={styles.page}>
      <Link className="skip-link" href="#readme-content">Skip to README</Link>
      <nav className={styles.navigation} aria-label="README navigation">
        <Link href="/">Elijah Peters<span>.</span></Link>
        <Link href="/#projects">← Back to portfolio</Link>
      </nav>
      <div className={styles.banner}>
        <p>THE PORTFOLIO README</p>
        <p>The problem. The approach.<br /><strong>The evidence behind the work.</strong></p>
        <span>Six questions per project, with findings and limitations stated openly.</span>
      </div>
      <article id="readme-content" className={styles.content}>
        <ReadmeContent source={projects} />
        <details className={styles.notes}>
          <summary>Repository, local setup &amp; contact details</summary>
          <ReadmeContent source={"## About this repository\n" + repositoryNotes} />
        </details>
      </article>
      <footer className={styles.footer}>
        <Link href="/#projects">Explore the project evidence →</Link>
        <Link href="/#contact">Discuss a role or project →</Link>
      </footer>
    </main>
  );
}
