"use client";

import { FormEvent, useState } from "react";

import styles from "../booking.module.css";

export type PassengerDetails = {
  type: "adult" | "child" | "infant_with_seat" | "infant_without_seat";
  title: "mr" | "ms" | "mrs" | "miss" | "dr";
  givenName: string;
  familyName: string;
  bornOn: string;
  gender: "m" | "f";
  email: string;
  phoneNumber: string;
  identityDocument?: {
    type: "passport";
    uniqueIdentifier: string;
    expiresOn: string;
    issuingCountryCode: string;
    nationality: string;
  };
};

export interface PassengerDetailsFormProps {
  passengerTypes: PassengerDetails["type"][];
  identityDocumentsRequired: boolean;
  onSubmit: (passengers: PassengerDetails[]) => void | Promise<void>;
  disabled?: boolean;
  isSubmitting?: boolean;
}

function emptyPassenger(
  type: PassengerDetails["type"],
): PassengerDetails {
  return {
    type,
    title: "mr",
    givenName: "",
    familyName: "",
    bornOn: "",
    gender: "m",
    email: "",
    phoneNumber: "",
  };
}

function passengerLabel(type: PassengerDetails["type"], index: number) {
  const label =
    type === "adult"
      ? "Adult"
      : type === "child"
        ? "Child"
        : type === "infant_with_seat"
          ? "Infant with seat"
          : "Infant on lap";
  return `${label} ${index + 1}`;
}

export default function PassengerDetailsForm({
  passengerTypes,
  identityDocumentsRequired,
  onSubmit,
  disabled = false,
  isSubmitting = false,
}: PassengerDetailsFormProps) {
  const [passengers, setPassengers] = useState(() =>
    passengerTypes.map(emptyPassenger),
  );

  const update = (
    index: number,
    values: Partial<PassengerDetails>,
  ) => {
    setPassengers((current) =>
      current.map((passenger, currentIndex) =>
        currentIndex === index ? { ...passenger, ...values } : passenger,
      ),
    );
  };

  const updateDocument = (
    index: number,
    values: Partial<NonNullable<PassengerDetails["identityDocument"]>>,
  ) => {
    setPassengers((current) =>
      current.map((passenger, currentIndex) => {
        if (currentIndex !== index) return passenger;
        return {
          ...passenger,
          identityDocument: {
            type: "passport",
            uniqueIdentifier: "",
            expiresOn: "",
            issuingCountryCode: "",
            nationality: "",
            ...passenger.identityDocument,
            ...values,
          },
        };
      }),
    );
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (disabled || isSubmitting) return;
    await onSubmit(passengers);
  };

  return (
    <form className={styles.passengerForm} onSubmit={submit}>
      <div className={styles.panelHeading}>
        <div>
          <p className={styles.kicker}>Passenger details</p>
          <h2>Who is travelling?</h2>
        </div>
      </div>
      <p className={styles.privacyNote}>
        Enter names exactly as shown on travel documents. SkyETA encrypts these
        details temporarily and uses them only to complete the airline booking.
        Card details stay on Paystack&apos;s secure checkout.
      </p>

      <div className={styles.passengerList}>
        {passengers.map((passenger, index) => (
          <fieldset className={styles.passengerCard} key={`${passenger.type}-${index}`}>
            <legend>{passengerLabel(passenger.type, index)}</legend>
            <div className={styles.passengerGrid}>
              <label className={styles.field}>
                <span>Title</span>
                <select
                  value={passenger.title}
                  onChange={(event) =>
                    update(index, {
                      title: event.target.value as PassengerDetails["title"],
                    })
                  }
                  required
                >
                  <option value="mr">Mr</option>
                  <option value="ms">Ms</option>
                  <option value="mrs">Mrs</option>
                  <option value="miss">Miss</option>
                  <option value="dr">Dr</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>First and middle names</span>
                <input
                  value={passenger.givenName}
                  onChange={(event) => update(index, { givenName: event.target.value })}
                  autoComplete="given-name"
                  maxLength={100}
                  required
                />
              </label>
              <label className={styles.field}>
                <span>Family name</span>
                <input
                  value={passenger.familyName}
                  onChange={(event) => update(index, { familyName: event.target.value })}
                  autoComplete="family-name"
                  maxLength={100}
                  required
                />
              </label>
              <label className={styles.field}>
                <span>Date of birth</span>
                <input
                  type="date"
                  value={passenger.bornOn}
                  onChange={(event) => update(index, { bornOn: event.target.value })}
                  autoComplete="bday"
                  required
                />
              </label>
              <label className={styles.field}>
                <span>Gender on document</span>
                <select
                  value={passenger.gender}
                  onChange={(event) =>
                    update(index, { gender: event.target.value as "m" | "f" })
                  }
                  required
                >
                  <option value="m">Male</option>
                  <option value="f">Female</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>Email</span>
                <input
                  type="email"
                  value={passenger.email}
                  onChange={(event) => update(index, { email: event.target.value })}
                  autoComplete="email"
                  maxLength={254}
                  required={index === 0}
                />
              </label>
              <label className={styles.field}>
                <span>Phone number</span>
                <input
                  type="tel"
                  value={passenger.phoneNumber}
                  onChange={(event) => update(index, { phoneNumber: event.target.value })}
                  autoComplete="tel"
                  placeholder="+234…"
                  maxLength={30}
                  required={index === 0}
                />
              </label>
            </div>

            {identityDocumentsRequired ? (
              <div className={styles.documentGrid}>
                <label className={styles.field}>
                  <span>Passport number</span>
                  <input
                    value={passenger.identityDocument?.uniqueIdentifier ?? ""}
                    onChange={(event) =>
                      updateDocument(index, { uniqueIdentifier: event.target.value })
                    }
                    autoComplete="off"
                    maxLength={40}
                    required
                  />
                </label>
                <label className={styles.field}>
                  <span>Passport expiry</span>
                  <input
                    type="date"
                    value={passenger.identityDocument?.expiresOn ?? ""}
                    onChange={(event) =>
                      updateDocument(index, { expiresOn: event.target.value })
                    }
                    required
                  />
                </label>
                <label className={styles.field}>
                  <span>Issuing country</span>
                  <input
                    value={passenger.identityDocument?.issuingCountryCode ?? ""}
                    onChange={(event) =>
                      updateDocument(index, {
                        issuingCountryCode: event.target.value.toUpperCase().slice(0, 2),
                      })
                    }
                    placeholder="NG"
                    maxLength={2}
                    required
                  />
                </label>
                <label className={styles.field}>
                  <span>Nationality</span>
                  <input
                    value={passenger.identityDocument?.nationality ?? ""}
                    onChange={(event) =>
                      updateDocument(index, {
                        nationality: event.target.value.toUpperCase().slice(0, 2),
                      })
                    }
                    placeholder="NG"
                    maxLength={2}
                    required
                  />
                </label>
              </div>
            ) : null}
          </fieldset>
        ))}
      </div>

      <button
        className={styles.primaryButton}
        type="submit"
        disabled={disabled || isSubmitting}
      >
        {isSubmitting ? "Preparing secure payment…" : "Continue to secure payment"}
      </button>
    </form>
  );
}
