"use client";

import { useEffect } from "react";

declare global {
  interface Window {
    umami?: {
      track: (event: string, data?: Record<string, string>) => void;
    };
  }
}

const SECTION_IDS = [
  "projects",
  "circuits",
  "about",
  "experience",
  "contact",
] as const;

export default function SectionAnalytics() {
  useEffect(() => {
    if (navigator.doNotTrack === "1" || !("IntersectionObserver" in window)) {
      return;
    }

    let cancelled = false;
    let observer: IntersectionObserver | undefined;
    let retryTimer: number | undefined;
    let retries = 0;
    let retryDelay = 250;
    const reported = new Set<string>();

    const start = () => {
      if (cancelled) return;

      if (!window.umami?.track) {
        if (retries < 7) {
          retries += 1;
          retryTimer = window.setTimeout(start, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 4_000);
        }
        return;
      }

      const targetSections = new Map<Element, string>();

      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            const section = targetSections.get(entry.target);
            if (!section || !entry.isIntersecting || reported.has(section)) {
              continue;
            }

            window.umami?.track("section-view", { section });
            reported.add(section);
            observer?.unobserve(entry.target);
          }
        },
        {
          rootMargin: "-20% 0px -55% 0px",
          threshold: 0,
        },
      );

      for (const sectionId of SECTION_IDS) {
        const section = document.getElementById(sectionId);
        if (!section) continue;

        const target = section.querySelector("h2, h3") ?? section;
        targetSections.set(target, sectionId);
        observer.observe(target);
      }
    };

    start();

    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      observer?.disconnect();
    };
  }, []);

  return null;
}
