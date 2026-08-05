import type { Metadata } from "next";
import Link from "next/link";

import PaymentReturnExperience from "../../components/PaymentReturnExperience";
import bookingStyles from "../../booking.module.css";
import styles from "../../skyeta.module.css";

export const metadata: Metadata = {
  title: "SkyETA Booking Confirmation",
  description: "Confirming a SkyETA flight booking.",
  robots: { index: false, follow: false },
};

const PAYSTACK_REFERENCE = /^[A-Za-z0-9.=-]{1,100}$/;

export default async function PaymentReturnPage({
  searchParams,
}: {
  searchParams:
    | Promise<Record<string, string | string[] | undefined>>
    | Record<string, string | string[] | undefined>;
}) {
  const query = await searchParams;
  const rawReference = Array.isArray(query.reference)
    ? query.reference[0]
    : query.reference;
  const rawTransactionReference = Array.isArray(query.trxref)
    ? query.trxref[0]
    : query.trxref;
  const candidate = rawReference ?? rawTransactionReference ?? "";
  const reference = PAYSTACK_REFERENCE.test(candidate) ? candidate : null;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link className={styles.backLink} href="/skyeta">
          <span aria-hidden="true">←</span> Back to SkyETA
        </Link>
        <span className={styles.systemState}>
          <i aria-hidden="true" /> Booking confirmation
        </span>
      </header>
      <div className={bookingStyles.checkoutPage}>
        <PaymentReturnExperience reference={reference} />
      </div>
    </main>
  );
}
