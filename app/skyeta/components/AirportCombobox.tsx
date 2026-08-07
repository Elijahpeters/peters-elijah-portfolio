"use client";

import {
  ChangeEvent,
  KeyboardEvent,
  PointerEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import styles from "./AirportCombobox.module.css";

type AirportOption = {
  code: string;
  name: string;
  city: string;
  countryCode: string;
  label: string;
};

type AirportResponse = {
  ok: boolean;
  airports?: AirportOption[];
};

export interface AirportComboboxProps {
  label: string;
  name: string;
  value: string;
  onChange: (iataCode: string) => void;
  error?: string;
  describedBy?: string;
}

const MIN_SEARCH_LENGTH = 2;
const DEBOUNCE_MS = 220;

function validOption(value: unknown): value is AirportOption {
  if (!value || typeof value !== "object") return false;
  const option = value as Partial<AirportOption>;
  return (
    typeof option.code === "string" &&
    /^[A-Z]{3}$/.test(option.code) &&
    typeof option.name === "string" &&
    option.name.length > 0 &&
    option.name.length <= 180 &&
    typeof option.city === "string" &&
    option.city.length <= 100 &&
    typeof option.countryCode === "string" &&
    (option.countryCode === "" || /^[A-Z]{2}$/.test(option.countryCode)) &&
    typeof option.label === "string" &&
    option.label.length <= 320
  );
}

function selectedDisplay(option: AirportOption): string {
  return `${option.city || option.name} (${option.code})`;
}

export default function AirportCombobox({
  label,
  name,
  value,
  onChange,
  error,
  describedBy,
}: AirportComboboxProps) {
  const generatedId = useId();
  const inputId = `${generatedId}-input`;
  const listboxId = `${generatedId}-listbox`;
  const hintId = `${generatedId}-hint`;
  const errorId = `${generatedId}-error`;
  const [query, setQuery] = useState(value);
  const [options, setOptions] = useState<AirportOption[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isOpen, setIsOpen] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [status, setStatus] = useState<
    "idle" | "loading" | "ready" | "empty" | "error"
  >("idle");
  const selectedRef = useRef<{ code: string; display: string } | null>(null);
  const lastValueRef = useRef(value);

  useEffect(() => {
    if (value === lastValueRef.current) return;
    lastValueRef.current = value;
    if (selectedRef.current?.code === value) return;
    selectedRef.current = null;
    setQuery(value);
    setOptions([]);
    setStatus("idle");
    setIsOpen(false);
  }, [value]);

  useEffect(() => {
    const trimmedQuery = query.trim();
    if (
      !isFocused ||
      trimmedQuery.length < MIN_SEARCH_LENGTH ||
      selectedRef.current?.display === query
    ) {
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setActiveIndex(-1);
      setStatus("loading");
      setIsOpen(true);
      try {
        const response = await fetch(
          `/api/skyeta/airports?q=${encodeURIComponent(trimmedQuery)}`,
          {
            method: "GET",
            headers: { Accept: "application/json" },
            credentials: "same-origin",
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error("airport_search_failed");
        const payload = (await response.json()) as AirportResponse;
        const nextOptions = Array.isArray(payload.airports)
          ? payload.airports.filter(validOption).slice(0, 8)
          : [];
        if (!payload.ok) throw new Error("airport_search_failed");

        setOptions(nextOptions);
        setActiveIndex(nextOptions.length > 0 ? 0 : -1);
        setStatus(nextOptions.length > 0 ? "ready" : "empty");
        setIsOpen(true);
      } catch {
        if (controller.signal.aborted) return;
        setOptions([]);
        setActiveIndex(-1);
        setStatus("error");
        setIsOpen(true);
      }
    }, DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [isFocused, query]);

  const choose = (option: AirportOption) => {
    const display = selectedDisplay(option);
    selectedRef.current = { code: option.code, display };
    lastValueRef.current = option.code;
    setQuery(display);
    setOptions([]);
    setActiveIndex(-1);
    setStatus("idle");
    setIsOpen(false);
    onChange(option.code);
  };

  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    const nextQuery = event.target.value.slice(0, 80);
    selectedRef.current = null;
    setQuery(nextQuery);
    setOptions([]);
    setActiveIndex(-1);
    setStatus("idle");
    setIsOpen(false);
    if (value) {
      lastValueRef.current = "";
      onChange("");
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setIsOpen(false);
      setActiveIndex(-1);
      return;
    }

    if (!isOpen || options.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) =>
        current <= 0 ? options.length - 1 : current - 1,
      );
    } else if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(options.length - 1);
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      choose(options[activeIndex]);
    } else if (event.key === "Tab") {
      setIsOpen(false);
    }
  };

  const commitTypedCode = () => {
    const typedCode = query.trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(typedCode) || value === typedCode) return;

    const exactOption = options.find((option) => option.code === typedCode);
    if (exactOption) {
      choose(exactOption);
    }
  };

  const handleOptionPointerDown = (
    event: PointerEvent<HTMLLIElement>,
    option: AirportOption,
  ) => {
    event.preventDefault();
    choose(option);
  };

  const describedByIds = [hintId, describedBy, error ? errorId : undefined]
    .filter(Boolean)
    .join(" ");
  const activeOptionId =
    isOpen && activeIndex >= 0
      ? `${generatedId}-option-${options[activeIndex]?.code}`
      : undefined;

  return (
    <div className={styles.root}>
      <label className={styles.label} htmlFor={inputId}>
        {label}
      </label>
      <div className={styles.control}>
        <input type="hidden" name={name} value={value} />
        <input
          id={inputId}
          className={styles.input}
          name={`${name}-search`}
          value={query}
          onChange={handleInput}
          onFocus={(event) => {
            setIsFocused(true);
            event.currentTarget.select();
          }}
          onBlur={() => {
            commitTypedCode();
            setIsFocused(false);
            setIsOpen(false);
          }}
          onKeyDown={handleKeyDown}
          placeholder="City or airport code"
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={isOpen}
          aria-activedescendant={activeOptionId}
          aria-invalid={Boolean(error)}
          aria-describedby={describedByIds}
        />
        {value ? <span className={styles.code}>{value}</span> : null}
      </div>

      <small id={hintId} className={styles.hint}>
        Search by city, airport name or three-letter code.
      </small>
      {error ? (
        <em id={errorId} className={styles.error}>
          {error}
        </em>
      ) : null}

      {isOpen ? (
        <ul
          id={listboxId}
          className={styles.listbox}
          role="listbox"
          aria-label={`${label} airport suggestions`}
        >
          {status === "loading" ? (
            <li className={styles.state} role="presentation">
              <span role="status">Searching airports…</span>
            </li>
          ) : null}
          {status === "empty" ? (
            <li className={styles.state} role="presentation">
              <span role="status">No matching airport found.</span>
            </li>
          ) : null}
          {status === "error" ? (
            <li className={styles.state} role="presentation">
              <span role="status">Airport search is unavailable right now.</span>
            </li>
          ) : null}
          {status === "ready"
            ? options.map((option, index) => (
                <li
                  id={`${generatedId}-option-${option.code}`}
                  key={option.code}
                  className={styles.option}
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseEnter={() => setActiveIndex(index)}
                  onPointerDown={(event) =>
                    handleOptionPointerDown(event, option)
                  }
                >
                  <span className={styles.optionCode}>{option.code}</span>
                  <span className={styles.optionDetails}>
                    <strong>{option.city || option.name}</strong>
                    <small>
                      {option.name}
                      {option.countryCode ? ` · ${option.countryCode}` : ""}
                    </small>
                  </span>
                </li>
              ))
            : null}
        </ul>
      ) : null}
    </div>
  );
}
