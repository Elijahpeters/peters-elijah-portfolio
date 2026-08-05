import assert from "node:assert/strict";
import test from "node:test";

import {
  PassengerValidationError,
  validatePassengerPayload,
} from "../app/lib/booking/passengers.ts";

const expected = [
  { id: "pas_adult", type: "adult" },
  { id: "pas_infant", type: "infant_without_seat" },
];

const passengers = [
  {
    type: "adult",
    title: "ms",
    givenName: "Amelia",
    familyName: "Earhart",
    bornOn: "1987-07-24",
    gender: "f",
    email: "Amelia@example.com",
    phoneNumber: "+2348012345678",
  },
  {
    type: "infant_without_seat",
    title: "miss",
    givenName: "Ada",
    familyName: "Earhart",
    bornOn: "2026-01-20",
    gender: "f",
    email: "",
    phoneNumber: "",
  },
];

test("passenger input is mapped to provider IDs without trusting browser IDs", () => {
  const result = validatePassengerPayload(passengers, expected, {
    identityDocumentsRequired: false,
    firstDepartureAt: "2026-09-10T09:30:00Z",
  });

  assert.equal(result.paymentEmail, "amelia@example.com");
  assert.equal(result.passengers[0].id, "pas_adult");
  assert.equal(result.passengers[0].infant_passenger_id, "pas_infant");
  assert.equal(result.passengers[1].id, "pas_infant");
  assert.equal("type" in result.passengers[0], false);
});

test("passenger type tampering is rejected", () => {
  assert.throws(
    () =>
      validatePassengerPayload(
        [{ ...passengers[0], type: "child" }, passengers[1]],
        expected,
        {
          identityDocumentsRequired: false,
          firstDepartureAt: "2026-09-10T09:30:00Z",
        },
      ),
    PassengerValidationError,
  );
});

test("age bands are checked against the travel date", () => {
  assert.throws(
    () =>
      validatePassengerPayload(
        [{ ...passengers[0], bornOn: "2020-01-01" }, passengers[1]],
        expected,
        {
          identityDocumentsRequired: false,
          firstDepartureAt: "2026-09-10T09:30:00Z",
        },
      ),
    /adult must be at least 12/i,
  );
});

test("required identity documents are normalized", () => {
  const result = validatePassengerPayload(
    [
      {
        ...passengers[0],
        identityDocument: {
          type: "passport",
          uniqueIdentifier: "A1234567",
          expiresOn: "2031-05-20",
          issuingCountryCode: "ng",
          nationality: "NG",
        },
      },
      {
        ...passengers[1],
        identityDocument: {
          type: "passport",
          uniqueIdentifier: "B1234567",
          expiresOn: "2031-05-20",
          issuingCountryCode: "ng",
          nationality: "NG",
        },
      },
    ],
    expected,
    {
      identityDocumentsRequired: true,
      firstDepartureAt: "2026-09-10T09:30:00Z",
    },
  );

  assert.deepEqual(result.passengers[0].identity_documents, [
    {
      type: "passport",
      unique_identifier: "A1234567",
      expires_on: "2031-05-20",
      issuing_country_code: "NG",
    },
  ]);
});

test("one responsible adult is required per lap infant", () => {
  assert.throws(
    () =>
      validatePassengerPayload(
        [passengers[1], { ...passengers[1], givenName: "Grace" }],
        [
          { id: "pas_infant_1", type: "infant_without_seat" },
          { id: "pas_infant_2", type: "infant_without_seat" },
        ],
        {
          identityDocumentsRequired: false,
          firstDepartureAt: "2026-09-10T09:30:00Z",
        },
      ),
    /responsible adult/i,
  );
});
