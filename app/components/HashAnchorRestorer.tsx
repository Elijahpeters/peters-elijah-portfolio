"use client";

import { useEffect } from "react";

const RESTORE_WINDOW_MS = 6_000;
const DEFERRED_CONTENT_EVENT = "portfolio:deferred-content-ready";

function findHashTarget() {
  const rawHash = window.location.hash.slice(1);
  if (!rawHash) return null;

  try {
    return document.getElementById(decodeURIComponent(rawHash));
  } catch {
    return document.getElementById(rawHash);
  }
}

function alignHashTarget() {
  const target = findHashTarget();
  if (!target) return;

  const root = document.documentElement;
  const previousScrollBehavior = root.style.scrollBehavior;
  root.style.scrollBehavior = "auto";
  target.scrollIntoView({ block: "start" });
  root.style.scrollBehavior = previousScrollBehavior;
}

export default function HashAnchorRestorer() {
  useEffect(() => {
    let activeUntil = 0;
    let frame = 0;

    const queueAlignment = () => {
      if (performance.now() > activeUntil || !window.location.hash) return;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(alignHashTarget);
    };

    const activate = () => {
      activeUntil = performance.now() + RESTORE_WINDOW_MS;
      queueAlignment();
    };

    const stopForUserScroll = () => {
      activeUntil = 0;
    };

    const stopForPointerInteraction = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest('a[href^="#"]')) return;
      stopForUserScroll();
    };

    const stopForNavigationKey = (event: KeyboardEvent) => {
      if (
        ["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End", " "].includes(
          event.key,
        )
      ) {
        stopForUserScroll();
      }
    };

    const resizeObserver = new ResizeObserver(queueAlignment);
    resizeObserver.observe(document.body);

    window.addEventListener("hashchange", activate);
    window.addEventListener(DEFERRED_CONTENT_EVENT, queueAlignment);
    window.addEventListener("pointerdown", stopForPointerInteraction, {
      passive: true,
    });
    window.addEventListener("wheel", stopForUserScroll, { passive: true });
    window.addEventListener("touchmove", stopForUserScroll, { passive: true });
    window.addEventListener("keydown", stopForNavigationKey);

    activate();

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      window.removeEventListener("hashchange", activate);
      window.removeEventListener(DEFERRED_CONTENT_EVENT, queueAlignment);
      window.removeEventListener("pointerdown", stopForPointerInteraction);
      window.removeEventListener("wheel", stopForUserScroll);
      window.removeEventListener("touchmove", stopForUserScroll);
      window.removeEventListener("keydown", stopForNavigationKey);
    };
  }, []);

  return null;
}

export { DEFERRED_CONTENT_EVENT };
