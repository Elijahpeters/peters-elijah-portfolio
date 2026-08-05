"use client";

import { lazy, Suspense, useEffect, useRef, useState } from "react";

const SkyetaDemo = lazy(() => import("./SkyetaDemo"));

function LoadingPanel() {
  return (
    <div className="skyeta-demo skyeta-demo--deferred" role="status">
      <span>Preparing the interactive SkyETA estimator...</span>
    </div>
  );
}

export default function DeferredSkyetaDemo({
  headingLevel = "h4",
}: {
  headingLevel?: "h2" | "h4";
}) {
  const boundaryRef = useRef<HTMLDivElement | null>(null);
  const [isNearViewport, setIsNearViewport] = useState(false);

  useEffect(() => {
    const boundary = boundaryRef.current;
    if (!boundary || !("IntersectionObserver" in window)) {
      setIsNearViewport(true);
      return;
    }

    const isSmallScreen = window.matchMedia("(max-width: 720px)").matches;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsNearViewport(true);
          observer.disconnect();
        }
      },
      { rootMargin: isSmallScreen ? "160px 0px" : "700px 0px" },
    );

    observer.observe(boundary);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={boundaryRef} className="skyeta-demo-boundary">
      {isNearViewport ? (
        <Suspense fallback={<LoadingPanel />}>
          <SkyetaDemo headingLevel={headingLevel} />
        </Suspense>
      ) : (
        <LoadingPanel />
      )}
    </div>
  );
}
