export const CONTACT_FIELD_ORDER = [
  "name",
  "email",
  "company",
  "reason",
  "message",
] as const;

export type ContactFieldName = (typeof CONTACT_FIELD_ORDER)[number];

type ContactErrors = Partial<Record<string, string>>;

type FormWithNamedElements = {
  elements: {
    namedItem(name: string): unknown;
  };
};

export function getFirstInvalidContactField(
  errors: ContactErrors,
): ContactFieldName | null {
  return CONTACT_FIELD_ORDER.find((field) => Boolean(errors[field])) ?? null;
}

export function focusFirstInvalidContactField(
  form: FormWithNamedElements,
  errors: ContactErrors,
): ContactFieldName | null {
  const field = getFirstInvalidContactField(errors);
  if (!field) return null;

  const control = form.elements.namedItem(field);
  if (
    typeof control === "object" &&
    control !== null &&
    "focus" in control &&
    typeof control.focus === "function"
  ) {
    control.focus();
    return field;
  }

  return null;
}
