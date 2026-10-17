/* eslint-disable @next/next/no-html-link-for-pages -- Full navigations load the latest published CMS revision. */
import { themeStyle } from '../../cms/design';
import Image from 'next/image';
import { notFound } from 'next/navigation';
import { getPublished } from '../../cms/storage';
import { contentMetadata } from '../../cms/metadata';
import Navigation from '../../cms/Navigation';
import styles from '../../cms/portfolio.module.css';
export const dynamic = 'force-dynamic';
type Props = {
  params: Promise<{
    slug: string;
  }>;
};
export async function generateMetadata({
  params
}: Props) {
  const c = await getPublished();
  const {
    slug
  } = await params;
  const p = [...c.projects, ...c.circuits].find(p => p.slug === slug);
  return p ? contentMetadata(c, `/work/${p.slug}`, `${p.title} | ${c.profile.alternateName}`, p.summary, p.image ? { url: p.image, alt: `${p.imageAlt} — project by ${c.profile.alternateName}` } : undefined) : {
    title: 'Project not found',
    robots: {
      index: false
    }
  };
}
export default async function ProjectPage({
  params
}: Props) {
  const c = await getPublished();
  const {
    slug
  } = await params;
  const p = [...c.projects, ...c.circuits].find(p => p.slug === slug);
  if (!p) notFound();
  return <div className={styles.portfolio} style={themeStyle(c.design)}><a className="skip-link" href="#project">Skip to project</a><Navigation brand={c.profile.brand} sections={c.design.sections} /><main id="project" className={styles.case}><a className={styles.inlineLink} href="/#projects">← All projects</a><p className={styles.eyebrow}>{p.category}</p><h1>{p.title}</h1><p>{p.summary}</p><p className={styles.status}>{p.status}</p><p className={styles.tools}>{p.tools}</p>{p.image && <Image src={p.image} alt={p.imageAlt} width={1000} height={620} unoptimized />}{p.sections.map((s, i) => <section key={i}><h2>{s.heading}</h2>{s.image && <Image src={s.image} alt={s.imageAlt} width={1000} height={650} unoptimized />}<p>{s.text}</p></section>)}<div className={styles.actions}>{p.evidenceUrl && <a className={styles.button} href={p.evidenceUrl}>Technical evidence ↗</a>}{p.sourceUrl && <a className={styles.secondaryButton} href={p.sourceUrl} target="_blank" rel="noreferrer">Source code ↗</a>}{p.demoUrl && <a className={styles.secondaryButton} href={p.demoUrl}>Open application ↗</a>}</div><p>Engineering work by {c.profile.fullName}, professionally known as {c.profile.alternateName}.</p></main></div>;
}
