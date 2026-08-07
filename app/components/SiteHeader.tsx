"use client";

import { useEffect, useRef, useState } from "react";

const navigationItems = [
  { href: "#experience", label: "Experience" },
  { href: "#projects", label: "Projects" },
  { href: "#circuits", label: "Circuit Lab" },
  { href: "#about", label: "Profile" },
  { href: "#contact", label: "Get in Touch", contact: true },
] as const;

function NavigationLinks({ onNavigate }: { onNavigate?: () => void }) {
  return navigationItems.map((item) => (
    <a
      className={"contact" in item && item.contact ? "header-contact" : undefined}
      href={item.href}
      key={item.href}
      onClick={onNavigate}
    >
      {item.label}
      {"contact" in item && item.contact ? (
        <span aria-hidden="true">↗</span>
      ) : null}
    </a>
  ));
}

export default function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const headerRef = useRef<HTMLElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      toggleRef.current?.focus();
    };
    const closeOutside = (event: PointerEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const closeAtDesktopWidth = (event: MediaQueryListEvent) => {
      if (event.matches) setMenuOpen(false);
    };
    const desktopQuery = window.matchMedia("(min-width: 821px)");

    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOutside);
    desktopQuery.addEventListener("change", closeAtDesktopWidth);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", closeOutside);
      desktopQuery.removeEventListener("change", closeAtDesktopWidth);
    };
  }, [menuOpen]);

  return (
    <header className="site-header" id="top" ref={headerRef}>
      <a className="brand" href="#top" aria-label="Peters Elijah, home">
        Peters Elijah<span>.</span>
      </a>

      <nav className="desktop-navigation" aria-label="Primary navigation">
        <NavigationLinks />
      </nav>

      <button
        className="navigation-toggle"
        type="button"
        aria-expanded={menuOpen}
        aria-controls="mobile-navigation"
        aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
        onClick={() => setMenuOpen((current) => !current)}
        ref={toggleRef}
      >
        <span>{menuOpen ? "Close" : "Menu"}</span>
        <i aria-hidden="true" />
      </button>

      <nav
        className="mobile-navigation"
        id="mobile-navigation"
        aria-label="Mobile navigation"
        hidden={!menuOpen}
      >
        <NavigationLinks onNavigate={() => setMenuOpen(false)} />
      </nav>
    </header>
  );
}
