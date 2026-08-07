"use client";

import { FormEvent, useId, useMemo, useState } from "react";

import type {
  CabinClass,
  DisplayCurrency,
  FlightProviderMode,
  FlightSearchValues,
} from "./flight-ui-types";
import AirportCombobox from "./AirportCombobox";
import ProviderModeBadge from "./ProviderModeBadge";
import styles from "../booking.module.css";

export interface FlightSearchFormProps {
  providerMode: FlightProviderMode;
  onSearch: (values: FlightSearchValues) => void | Promise<void>;
  initialValues?: Partial<FlightSearchValues>;
  isSearching?: boolean;
  onCancelSearch?: () => void;
  providerName?: string;
}

type FormErrors = Partial<Record<keyof FlightSearchValues, string>>;

const cabinOptions: Array<{ value: CabinClass; label: string }> = [
  { value: "economy", label: "Economy" },
  { value: "premium_economy", label: "Premium economy" },
  { value: "business", label: "Business" },
  { value: "first", label: "First" },
];

const displayCurrencyOptions: Array<{ value: DisplayCurrency; label: string }> = [
  { value: "NGN", label: "NGN — provider price" },
  { value: "USD", label: "USD — estimated" },
  { value: "GBP", label: "GBP — estimated" },
  { value: "EUR", label: "EUR — estimated" },
];

function todayAsInputValue() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function validate(values: FlightSearchValues, today: string): FormErrors {
  const next: FormErrors = {};

  if (!/^[A-Z]{3}$/.test(values.origin)) {
    next.origin = "Choose an origin airport from the suggestions.";
  }
  if (!/^[A-Z]{3}$/.test(values.destination)) {
    next.destination = "Choose a destination airport from the suggestions.";
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
  onCancelSearch,
  providerName = "the connected flight provider",
}: FlightSearchFormProps) {
  const formId = useId();
  const today = useMemo(() => todayAsInputValue(), []);
  const [errors, setErrors] = useState<FormErrors>({});
  const [tripType, setTripType] = useState<"one-way" | "round-trip">(
    initialValues?.returnDate ? "round-trip" : "one-way",
  );
  const [values, setValues] = useState<FlightSearchValues>({
    origin: initialValues?.origin ?? "",
    destination: initialValues?.destination ?? "",
    departureDate: initialValues?.departureDate ?? "",
    returnDate: initialValues?.returnDate ?? "",
    adults: initialValues?.adults ?? 1,
    children: initialValues?.children ?? 0,
    infants: initialValues?.infants ?? 0,
    cabin: initialValues?.cabin ?? "economy",
    displayCurrency: initialValues?.displayCurrency ?? "NGN",
  });

  const isConnected = providerMode !== "unconfigured";
  const submitLabel =
    providerMode === "unconfigured" ? "Flight search unavailable" : "Search flights";

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
    if (tripType === "round-trip" && !values.returnDate) {
      nextErrors.returnDate = "Choose a return date.";
    }
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
          <p className={styles.kicker}>Find flights worldwide</p>
          <h2 id="flight-search-title">Where are you going?</h2>
        </div>
        <ProviderModeBadge mode={providerMode} />
      </div>

      {providerMode === "live" ? (
        <p className={styles.providerDisclosure}>
          Prices supplied by <strong>{providerName}</strong>. SkyETA compares
          the returned options but does not sell the ticket.
        </p>
      ) : null}

      {providerMode !== "live" ? (
        <p className={styles.modeNotice} role="status">
          {providerMode === "test"
            ? "This environment shows clearly labelled provider test data; its schedules and prices are not real."
            : "Connect and verify a production flight provider to enable fare search."}
        </p>
      ) : null}

      <fieldset className={styles.tripTypeControl}>
        <legend>Trip type</legend>
        <button
          type="button"
          aria-pressed={tripType === "one-way"}
          onClick={() => {
            setTripType("one-way");
            setValues((current) => ({ ...current, returnDate: "" }));
            setErrors((current) => ({ ...current, returnDate: undefined }));
          }}
        >
          One way
        </button>
        <button
          type="button"
          aria-pressed={tripType === "round-trip"}
          onClick={() => setTripType("round-trip")}
        >
          Round trip
        </button>
      </fieldset>

      <div className={styles.routeFields}>
        <AirportCombobox
          label="From"
          name="origin"
          value={values.origin}
          error={errors.origin}
          onChange={(origin) => {
            setValues((current) => ({ ...current, origin }));
            setErrors((current) => ({ ...current, origin: undefined }));
          }}
        />

        <span className={styles.routeArrow} aria-hidden="true">
          →
        </span>

        <AirportCombobox
          label="To"
          name="destination"
          value={values.destination}
          error={errors.destination}
          onChange={(destination) => {
            setValues((current) => ({ ...current, destination }));
            setErrors((current) => ({ ...current, destination: undefined }));
          }}
        />
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

        {tripType === "round-trip" ? (
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
              required
            />
            {errors.returnDate ? (
              <em
                id={`${formId}-return-date-error`}
                className={styles.fieldError}
              >
                {errors.returnDate}
              </em>
            ) : null}
          </label>
        ) : null}
      </div>

      <fieldset className={styles.passengerFields}>
        <legend>Passengers</legend>
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

      </fieldset>

      <p className={styles.passengerNotice}>
        Lap infants are supported by the current provider. For an infant with a
        separate seat, complete the search directly with the airline.
      </p>

      <div className={styles.travelPreferences}>
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

        <label className={styles.field}>
          <span>Display currency</span>
          <select
            name="displayCurrency"
            value={values.displayCurrency}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                displayCurrency: event.target.value as DisplayCurrency,
              }))
            }
          >
            {displayCurrencyOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <small>
            Converted amounts are estimates; the provider currency remains final.
          </small>
        </label>
      </div>

      <div className={styles.searchActions}>
        <button
          className={styles.primaryButton}
          type="submit"
          disabled={!isConnected || isSearching}
        >
          {isSearching ? "Searching flights…" : submitLabel}
          <span aria-hidden="true">→</span>
        </button>
        {isSearching && onCancelSearch ? (
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onCancelSearch}
          >
            Cancel search
          </button>
        ) : null}
      </div>
    </form>
  );
}
