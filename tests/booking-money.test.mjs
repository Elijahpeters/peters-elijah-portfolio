import assert from "node:assert/strict";
import test from "node:test";

import {
  currencyMinorUnit,
  minorUnitsToMoney,
  moneyToMinorUnits,
} from "../app/lib/booking/money.ts";

test("fare amounts use the correct ISO currency exponent", () => {
  assert.equal(currencyMinorUnit("USD"), 2);
  assert.equal(currencyMinorUnit("JPY"), 0);
  assert.equal(currencyMinorUnit("KWD"), 3);
  assert.equal(
    moneyToMinorUnits({ amount: "109.20", currency: "USD" }),
    10_920,
  );
  assert.equal(
    moneyToMinorUnits({ amount: "9500", currency: "JPY" }),
    9_500,
  );
  assert.equal(
    moneyToMinorUnits({ amount: "12.345", currency: "KWD" }),
    12_345,
  );
  assert.deepEqual(minorUnitsToMoney(10_920, "USD"), {
    amount: "109.20",
    currency: "USD",
  });
});

test("fare amounts reject precision that cannot be represented exactly", () => {
  assert.throws(
    () => moneyToMinorUnits({ amount: "10.001", currency: "USD" }),
    /unsupported precision/,
  );
});
