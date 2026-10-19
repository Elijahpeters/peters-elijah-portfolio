"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./WorkIntroduction.module.css";

/** A non-modal introduction: the page remains usable while it is open. */
export default function WorkIntroduction() {
  const [open, setOpen] = useState(true);
  const [engaged, setEngaged] = useState(false);
  const [attention, setAttention] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const reopen = useRef<HTMLButtonElement>(null);
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open || engaged) return;
    // One reminder only, cancelled as soon as the visitor interacts.
    const timer = window.setTimeout(() => setAttention(true), 10_000);
    return () => window.clearTimeout(timer);
  }, [open, engaged]);

  function dismiss() {
    const restoreFocus = panel.current?.contains(document.activeElement);
    setOpen(false);
    if (restoreFocus) window.requestAnimationFrame(() => reopen.current?.focus());
  }

  useEffect(() => {
    if (!open) return;
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") dismiss();
    }
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [open]);

  function engage() {
    setEngaged(true);
    setAttention(false);
  }

  return open ? (
    <aside
      className={`${styles.panel} ${attention ? styles.attention : ""}`}
      aria-labelledby="work-introduction-title"
      ref={panel}
      onPointerEnter={engage}
      onPointerDown={engage}
      onFocusCapture={engage}
    >
      <div className={styles.topline}>
        <span>A QUICK INTRODUCTION</span>
        <button ref={close} type="button" onClick={dismiss} aria-label="Close introduction">×</button>
      </div>
      <p className={styles.name}>Hi, I’m Elijah Peters.</p>
      <h2 id="work-introduction-title">Hardware meets<br /><em>applied intelligence.</em></h2>
      <p className={styles.summary}>I’m an Electrical &amp; Electronics Engineer. I design and simulate circuits, develop embedded systems, and apply AI/ML to engineering problems.</p>
      <ul className={styles.work}>
        <li><span>01</span><div><strong>Circuits &amp; hardware</strong><p>Circuit simulation, PCB development and power electronics.</p></div></li>
        <li><span>02</span><div><strong>Connected systems</strong><p>Embedded control, biometric access and hardware/software integration.</p></div></li>
        <li><span>03</span><div><strong>Applied AI &amp; ML</strong><p>Computer vision, flight intelligence and AI model evaluation.</p></div></li>
      </ul>
      <div className={styles.actions}>
        <a href="#projects" onClick={dismiss}>Explore my work <span aria-hidden="true">↗</span></a>
        <a href="#contact" onClick={dismiss}>Get in touch</a>
      </div>
      <p className={styles.hint}>Projects include the problem, approach, evidence and limitations.</p>
    </aside>
  ) : (
    <button
      className={styles.reopen}
      type="button"
      ref={reopen}
      onClick={() => {
        setOpen(true);
        setEngaged(true);
        setAttention(false);
        window.requestAnimationFrame(() => close.current?.focus());
      }}
    >About my work <span aria-hidden="true">↗</span></button>
  );
}
