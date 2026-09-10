/** Telling password managers which fields are not credentials. */

/**
 * Props that ask every password manager to leave a field alone.
 *
 * A field whose label or placeholder mentions a password gets treated as a credential: the
 * manager offers to fill it in, and — worse — decides the form around it is a login form and
 * offers to save one when it is submitted. Wording alone is not enough to prevent that, because
 * the heuristics also weigh a field's neighbours, so the fields say so outright.
 *
 * Four vendors, four spellings, none of which validate against the others. Deliberately not
 * applied to lifeline's own login form, which wants exactly this behaviour.
 */
export const notACredential = {
  autoComplete: "off",
  "data-bwignore": true,
  "data-1p-ignore": true,
  "data-lpignore": "true",
  "data-form-type": "other",
} as const;
