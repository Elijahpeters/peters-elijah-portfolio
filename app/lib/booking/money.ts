import type { Money } from "../../types/flight-booking";

const ZERO_DECIMAL_CURRENCIES = new Set([
  "BIF",
  "CLP",
  "DJF",
  "GNF",
  "JPY",
  "KMF",
  "KRW",
  "PYG",
  "RWF",
  "UGX",
  "VND",
  "VUV",
  "XAF",
  "XOF",
  "XPF",
]);

const THREE_DECIMAL_CURRENCIES = new Set([
  "BHD",
  "IQD",
  "JOD",
  "KWD",
  "LYD",
  "OMR",
  "TND",
]);

export function currencyMinorUnit(currency: string): number {
  const code = currency.toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) {
    throw new TypeError("The fare currency is invalid.");
  }
  if (ZERO_DECIMAL_CURRENCIES.has(code)) return 0;
  if (THREE_DECIMAL_CURRENCIES.has(code)) return 3;
  return 2;
}

export function moneyToMinorUnits(money: Money): number {
  const match = money.amount.match(/^(0|[1-9]\d*)(?:\.(\d+))?$/);
  if (!match) throw new TypeError("The fare amount is invalid.");

  const exponent = currencyMinorUnit(money.currency);
  const fraction = match[2] ?? "";
  if (fraction.length > exponent && /[1-9]/.test(fraction.slice(exponent))) {
    throw new TypeError("The fare amount has unsupported precision.");
  }
  const normalizedFraction = fraction.slice(0, exponent).padEnd(exponent, "0");
  const value = BigInt(match[1]) * BigInt(10) ** BigInt(exponent) +
    BigInt(normalizedFraction || "0");
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new RangeError("The fare amount is too large.");
  }
  return Number(value);
}

export function minorUnitsToMoney(amount: number, currency: string): Money {
  if (!Number.isSafeInteger(amount) || amount < 0) {
    throw new TypeError("The stored fare amount is invalid.");
  }
  const code = currency.toUpperCase();
  const exponent = currencyMinorUnit(code);
  if (exponent === 0) return { amount: String(amount), currency: code };
  const digits = String(amount).padStart(exponent + 1, "0");
  return {
    amount: `${digits.slice(0, -exponent)}.${digits.slice(-exponent)}`,
    currency: code,
  };
}
