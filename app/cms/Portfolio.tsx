/* eslint-disable @next/next/no-html-link-for-pages -- Full navigations load the latest published CMS revision. */
import Image from 'next/image';
import { Fragment } from 'react';
import { themeStyle } from './design';
import type { Content } from './content';
import Navigation from './Navigation';
import { personSchema } from './metadata';
import ContactForm from '../components/ContactForm';
import styles from './portfolio.module.css';
export default function Portfolio({
  content: c,
  preview = false
}: {
  content: Content;
  preview?: boolean;
}) {
  const p = c.profile;
  const settings = (type: string) => c.design.sections.find(s => s.type === type)!;
  const blocks: Record<string, () => React.ReactNode> = {
    'hero': () => <section id="hero" className={styles.hero} aria-labelledby="hero-heading">
    <div className={styles.heroCopy}><p className={styles.eyebrow}><span /> {p.role}</p><h1 id="hero-heading">{p.headline}</h1><p className={styles.introduction}>{p.introduction}</p><p className={styles.identity}>{p.fullName}, professionally known as {p.alternateName}.</p><div className={styles.actions}><a className={styles.button} href={c.design.sections.some(s => s.type === 'projects' && s.visible === 'yes') ? '#projects' : '#main-content'}>Explore my work <span aria-hidden="true">↗</span></a><a className={styles.secondaryButton} href={p.cv} download>Download CV <span aria-hidden="true">↓</span></a></div><p className={styles.location}>{p.location} <span>Electronics · Embedded systems · Applied AI</span></p></div>
    <figure className={styles.portrait}><Image src={p.portrait} alt={p.portraitAlt} width={1229} height={1536} priority unoptimized /><figcaption><span>{p.alternateName}</span><span>Engineer & builder</span></figcaption></figure>
   </section>,
    'capabilities': () => <section className={styles.section} id="what-i-build"><div className={styles.sectionTop}><p className={styles.eyebrow}>{settings('capabilities').label}</p><div><h2>{settings('capabilities').heading}</h2>{settings('capabilities').text && <p>{settings('capabilities').text}</p>}</div></div><div className={styles.capabilities}>{c.capabilities.map((item, i) => <article key={i}><span className={styles.index}>0{i + 1}</span><h3>{item.title}</h3><p>{item.text}</p></article>)}</div></section>,
    'projects': () => <section className={styles.section} id="projects"><div className={styles.sectionTop}><p className={styles.eyebrow}>{settings('projects').label}</p><div><h2>{settings('projects').heading}</h2><p>{settings('projects').text}</p></div></div><div className={styles.projects}>{c.projects.map((project, i) => <article className={styles.project} key={project.slug} id={project.slug}><a className={styles.projectVisual} href={`/work/${project.slug}`} tabIndex={-1} aria-hidden="true">{project.image && <Image src={project.image} alt="" width={900} height={560} unoptimized />}<span className={styles.projectNumber}>0{i + 1}</span></a><div className={styles.projectCopy}><p className={styles.eyebrow}>{project.category}</p><h3><a href={`/work/${project.slug}`}>{project.title} <span aria-hidden="true">↗</span></a></h3><p>{project.summary}</p><p className={styles.status}>{project.status}</p><p className={styles.tools}>{project.tools}</p><a className={styles.inlineLink} href={`/work/${project.slug}`}>Explore project <span aria-hidden="true">→</span></a></div></article>)}</div></section>,
    'circuits': () => <section className={styles.section} id="circuits"><div className={styles.sectionTop}><p className={styles.eyebrow}>{settings('circuits').label}</p><div><h2>{settings('circuits').heading}</h2><p>{settings('circuits').text}</p></div></div><div className={styles.circuits}>{c.circuits.map((study, i) => <a key={study.slug} href={`/work/${study.slug}`}><span>0{i + 1}</span><div><h3>{study.title}</h3><p>{study.category}</p></div><span aria-hidden="true">↗</span></a>)}</div><a className={styles.inlineLink} href="/projects/circuits">View all circuit evidence →</a></section>,
    'experience': () => <section className={`${styles.section} ${styles.experience}`} id="experience"><div className={styles.sectionTop}><p className={styles.eyebrow}>{settings('experience').label}</p><h2>{settings('experience').heading}</h2>{settings('experience').text && <p>{settings('experience').text}</p>}</div><div>{c.experience.map((item, i) => <article className={styles.role} key={i}><p>{item.period}</p><div><h3>{item.role}</h3><strong>{item.company}</strong><p>{item.summary}</p></div></article>)}</div></section>,
    'about': () => <section className={styles.section} id="about"><div className={styles.sectionTop}><p className={styles.eyebrow}>{settings('about').label}</p><div><h2>{settings('about').heading}</h2><p className={styles.about}>{settings('about').text || p.about}</p></div></div><div className={styles.skills}>{c.skills.map((item, i) => <article key={i}><h3>{item.title}</h3><p>{item.text}</p></article>)}</div></section>,
    'contact': () => <section className={styles.contact} id="contact"><div><p className={styles.eyebrow}>{settings('contact').label}</p><h2>{p.contactHeading}</h2><p>{p.contactText}</p><a className={styles.email} href={`mailto:${p.email}`}>{p.email} ↗</a><div className={styles.socials}><a href={p.linkedin} target="_blank" rel="noreferrer">LinkedIn ↗</a><a href={p.github} target="_blank" rel="noreferrer">GitHub ↗</a><a href={p.cv} download>CV ↓</a>{p.phone && <a href={`tel:${p.phone}`}>Call me ↗</a>}</div></div><ContactForm contactEmail={p.email} /></section>
  };
  return <div className={styles.portfolio} style={themeStyle(c.design)} data-hero={c.design.heroLayout} data-projects={c.design.projectLayout}>
  <a className="skip-link" href="#main-content">Skip to main content</a>
  {!preview && <script type="application/ld+json" dangerouslySetInnerHTML={{
      __html: JSON.stringify(personSchema(c)).replace(/</g, '\\u003c')
    }} />}
  {preview && <div className={styles.previewBanner}>Private draft preview — these edits are not published. <a href="/admin">Return to dashboard</a></div>}
  <Navigation brand={p.brand} sections={c.design.sections} />
  <main id="main-content">
   {c.design.sections.filter(section => section.visible === 'yes').map(section => <Fragment key={section.id}>{section.type === 'custom' ? <section className={`${styles.section} ${styles.custom}`} data-layout={section.layout} id={section.id}><div><p className={styles.eyebrow}>{section.label}</p><h2>{section.heading}</h2><p>{section.text}</p>{section.buttonUrl && <a className={styles.button} href={section.buttonUrl}>{section.buttonLabel || 'Learn more'} ↗</a>}</div>{section.image && <Image src={section.image} alt={section.imageAlt} width={900} height={650} unoptimized />}</section> : blocks[section.type]?.()}</Fragment>)}
  </main>
  <footer className={styles.footer}><a href="/" className={styles.brand}>{p.brand}<span>.</span></a><p>© {new Date().getFullYear()} · {p.role}</p><a href="#main-content">Back to top ↑</a></footer>
 </div>;
}
