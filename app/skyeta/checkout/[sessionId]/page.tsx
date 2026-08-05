import type { Metadata } from "next";
import Link from "next/link";

import CheckoutExperience from "../../components/CheckoutExperience";
import styles from "../../skyeta.module.css";
import bookingStyles from "../../booking.module.css";

export const metadata: Metadata = {
  title: "SkyETA Checkout",
  description: "Review a selected SkyETA itinerary before secure payment.",
  robots: { index: false, follow: false },
};

export default async function CheckoutPage({
  params,
}: {
  params: Promise<{ sessionId: string }> | { sessionId: string };
}) {
  const { sessionId } = await params;
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link className={styles.backLink} href="/skyeta">
          <span aria-hidden="true">←</span> Back to flight search
        </Link>
        <span className={styles.systemState}>
          <i aria-hidden="true" /> Secure checkout
        </span>
      </header>
      <section className={bookingStyles.checkoutPage}>
        <CheckoutExperience sessionId={sessionId} />
      </section>
    </main>
  );
}
