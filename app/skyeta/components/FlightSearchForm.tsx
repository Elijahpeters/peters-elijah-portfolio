"use client";

import { FormEvent, useId, useMemo, useState } from "react";

import type {
  CabinClass,
  FlightProviderMode,
  FlightSearchValues,
} from "./flight-ui-types";
import ProviderModeBadge from "./ProviderModeBadge";
import styles from "../booking.module.css";

export interface FlightSearchFormProps {
  providerMode: FlightProviderMode;
  onSearch: (values: FlightSearchValues) => void | Promise<void>;
  initialValues?: Partial<FlightSearchValues>;
  isSearching?: boolean;
}

type FormErrors = Partial<Record<keyof FlightSearchValues, string>>;

const cabinOptions: Array<{ value: CabinClass; label: string }> = [
  { value: "economy", label: "Economy" },
  { value: "premium_economy", label: "Premium economy" },
  { value: "business", label: "Business" },
  { value: "first", label: "First" },
];

function todayAsInputValue() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function normalizeIata(value: string) {
  return value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
}

function validate(values: FlightSearchValues, today: string): FormErrors {
  const next: FormErrors = {};

  if (!/^[A-Z]{3}$/.test(values.origin)) {
    next.origin = "Enter a three-letter airport code, such as LOS.";
  }
  if (!/^[A-Z]{3}$/.test(values.destination)) {
    next.destination = "Enter a three-letter airport code, such as LHR.";
  }
  if (values.origin && values.origin === values.destination) {
    next.destination = "Choose a destination different from the origin.";
  }
  if (!values.departureDate) {
    next.departureDate = "Choose a departure date.";
  } else if (values.departureDate < today) {
    next.departureDate = "Departure cannot be in the past.";
  }
  if (values.returnDate && values.returnDate < values.departureDate) {
    next.returnDate = "Return must be on or after departure.";
  }
  if (values.adults < 1) {
    next.adults = "At least one adult is required.";
  }
  if (values.infants > values.adults) {
    next.infants = "Each infant must travel with an adult.";
  }
  if (values.adults + values.children + values.infants > 9) {
    next.adults = "A search can include at most nine passengers.";
  }

  return next;
}

export default function FlightSearchForm({
  providerMode,
  onSearch,
  initialValues,
  isSearching = false,
}: FlightSearchFormProps) {
  const formId = useId();
  const today = useMemo(() => todayAsInputValue(), []);
  const [errors, setErrors] = useState<FormErrors>({});
  const [values, setValues] = useState<FlightSearchValues>({
    origin: initialValues?.origin ?? "",
    destination: initialValues?.destination ?? "",
    departureDate: initialValues?.departureDate ?? "",
    returnDate: initialValues?.returnDate ?? "",
    adults: initialValues?.adults ?? 1,
    children: initialValues?.children ?? 0,
    infants: initialValues?.infants ?? 0,
    cabin: initialValues?.cabin ?? "economy",
  });

  const isConnected = providerMode !== "unconfigured";
  const submitLabel =
    providerMode === "live"
      ? "Search provider fares"
      : providerMode === "test"
        ? "Search test inventory"
        : "Fare search unavailable";

  const setCount = (
    field: "adults" | "children" | "infants",
    value: string,
  ) => {
    setValues((current) => ({
      ...current,
      [field]: Number.parseInt(value, 10),
    }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isConnected || isSearching) return;

    const nextErrors = validate(values, today);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    await onSearch({
      ...values,
      returnDate: values.returnDate || undefined,
    });
  };

  return (
    <form
      className={styles.searchPanel}
      onSubmit={handleSubmit}
      aria-busy={isSearching}
      noValidate
    >
      <div className={styles.panelHeading}>
        <div>
          <p className={styles.kicker}>Find a flight</p>
          <h2>Where are you going?</h2>
        </div>
        <ProviderModeBadge mode={providerMode} />
      </div>

      {providerMode !== "live" ? (
        <p className={styles.modeNotice} role="status">
          {providerMode === "test"
            ? "This environment shows clearly labelled provider test data; its schedules and prices are not real."
            : "Connect and verify a production flight provider to enable fare search."}
        </p>
      ) : null}

      <div className={styles.routeFields}>
        <label className={styles.field}>
          <span>From</span>
          <input
            name="origin"
            value={values.origin}
            onChange={(event) => {
              setValues((current) => ({
                ...current,
                origin: normalizeIata(event.target.value),
              }));
              setErrors((current) => ({ ...current, origin: undefined }));
            }}
            placeholder="LOS"
            autoComplete="off"
            inputMode="text"
            maxLength={3}
            aria-invalid={Boolean(errors.origin)}
            aria-describedby={errors.origin ? `${formId}-origin-error` : undefined}
            required
          />
          <small>Airport code</small>
          {errors.origin ? (
            <em id={`${formId}-origin-error`} className={styles.fieldError}>
              {errors.origin}
            </em>
          ) : null}
        </label>

        <span className={styles.routeArrow} aria-hidden="true">
          →
        </span>

        <label className={styles.field}>
          <span>To</span>
          <input
            name="destination"
            value={values.destination}
            onChange={(event) => {
              setValues((current) => ({
                ...current,
                destination: normalizeIata(event.target.value),
              }));
              setErrors((current) => ({
                ...current,
                destination: undefined,
              }));
            }}
            placeholder="LHR"
            autoComplete="off"
            inputMode="text"
            maxLength={3}
            aria-invalid={Boolean(errors.destination)}
            aria-describedby={
              errors.destination ? `${formId}-destination-error` : undefined
            }
            required
          />
          <small>Airport code</small>
          {errors.destination ? (
            <em
              id={`${formId}-destination-error`}
              className={styles.fieldError}
            >
              {errors.destination}
            </em>
          ) : null}
        </label>
      </div>

      <div className={styles.dateFields}>
        <label className={styles.field}>
          <span>Departure</span>
          <input
            type="date"
            name="departureDate"
            min={today}
            value={values.departureDate}
            onChange={(event) => {
              setValues((current) => ({
                ...current,
                departureDate: event.target.value,
              }));
              setErrors((current) => ({
                ...current,
                departureDate: undefined,
              }));
            }}
            aria-invalid={Boolean(errors.departureDate)}
            aria-describedby={
              errors.departureDate
                ? `${formId}-departure-date-error`
                : undefined
            }
            required
          />
          {errors.departureDate ? (
            <em
              id={`${formId}-departure-date-error`}
              className={styles.fieldError}
            >
              {errors.departureDate}
            </em>
          ) : null}
        </label>

        <label className={styles.field}>
          <span>Return</span>
          <input
            type="date"
            name="returnDate"
            min={values.departureDate || today}
            value={values.returnDate}
            onChange={(event) => {
              setValues((current) => ({
                ...current,
                returnDate: event.target.value,
              }));
              setErrors((current) => ({
                ...current,
                returnDate: undefined,
              }));
            }}
            aria-invalid={Boolean(errors.returnDate)}
            aria-describedby={
              errors.returnDate ? `${formId}-return-date-error` : undefined
            }
          />
          <small>Optional for one-way trips</small>
          {errors.returnDate ? (
            <em
              id={`${formId}-return-date-error`}
              className={styles.fieldError}
            >
              {errors.returnDate}
            </em>
          ) : null}
        </label>
      </div>

      <fieldset className={styles.passengerFields}>
        <legend>Passengers and cabin</legend>
        <label className={styles.field}>
          <span>Adults</span>
          <select
            name="adults"
            value={values.adults}
            onChange={(event) => setCount("adults", event.target.value)}
            aria-invalid={Boolean(errors.adults)}
            aria-describedby={errors.adults ? `${formId}-adults-error` : undefined}
          >
            {Array.from({ length: 9 }, (_, index) => index + 1).map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
          {errors.adults ? (
            <em id={`${formId}-adults-error`} className={styles.fieldError}>
              {errors.adults}
            </em>
          ) : null}
        </label>

        <label className={styles.field}>
          <span>Children</span>
          <select
            name="children"
            value={values.children}
            onChange={(event) => setCount("children", event.target.value)}
          >
            {Array.from({ length: 9 }, (_, index) => index).map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
          <small>Age 2–11</small>
        </label>

        <label className={styles.field}>
          <span>Infants</span>
          <select
            name="infants"
            value={values.infants}
            onChange={(event) => setCount("infants", event.target.value)}
            aria-invalid={Boolean(errors.infants)}
            aria-describedby={
              errors.infants ? `${formId}-infants-error` : undefined
            }
          >
            {Array.from({ length: 9 }, (_, index) => index).map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
          <small>Under 2, on lap</small>
          {errors.infants ? (
            <em id={`${formId}-infants-error`} className={styles.fieldError}>
              {errors.infants}
            </em>
          ) : null}
        </label>

        <label className={styles.field}>
          <span>Cabin</span>
          <select
            name="cabin"
            value={values.cabin}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                cabin: event.target.value as CabinClass,
              }))
            }
          >
            {cabinOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </fieldset>

      <button
        className={styles.primaryButton}
        type="submit"
        disabled={!isConnected || isSearching}
      >
        {isSearching ? "Searching verified inventory…" : submitLabel}
        <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}
