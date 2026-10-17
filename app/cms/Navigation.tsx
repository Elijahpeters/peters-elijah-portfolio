/* eslint-disable @next/next/no-html-link-for-pages -- Full navigations load the latest published CMS revision. */
'use client';

import { useState, useEffect, useRef } from 'react';
import type { Section } from './content';
import styles from './portfolio.module.css';
export default function Navigation({
  brand,
  sections
}: {
  brand: string;
  sections?: Section[];
}) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        toggle.current?.focus();
      }
    };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, []);
  return <header className={styles.navigation}><a className={styles.brand} href="/">{brand}<span>.</span></a><button className={styles.menu} ref={toggle} aria-expanded={open} aria-controls="portfolio-navigation" onClick={() => setOpen(!open)}>{open ? 'Close' : 'Menu'} <span aria-hidden="true">{open ? '−' : '+'}</span></button><nav id="portfolio-navigation" className={open ? styles.open : ''} aria-label="Main navigation">{(sections ? sections.filter(s => s.visible === 'yes' && s.type !== 'hero') : [{
        id: 'projects',
        label: 'Work'
      }, {
        id: 'experience',
        label: 'Experience'
      }, {
        id: 'about',
        label: 'About'
      }, {
        id: 'contact',
        label: 'Contact'
      }]).map(s => <a key={s.id} onClick={() => setOpen(false)} href={`/#${s.id}`}>{s.label}</a>)}</nav></header>;
}
