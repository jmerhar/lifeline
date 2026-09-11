/**
 * The languages a site can be asked to answer in.
 *
 * Every ISO 639-1 language, plus the locales of those that are served differently from one
 * country to another — a site with a Brazilian and a Portuguese edition answers on this
 * distinction, and asking for bare `pt` leaves the choice to the site.
 *
 * The names come from the browser's own language data rather than from a list kept here, which
 * is what keeps two hundred entries from being two hundred chances to misspell something.
 */

export interface Language {
  /** The BCP 47 tag asked for first. */
  tag: string;
  /** What the language is called in the interface. */
  label: string;
}

// The two-letter code of every language ISO 639-1 assigns one to.
const PRIMARY = `
  aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy
  da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu
  hy hz ia id ie ig ii ik in io is it iu iw ja ji jv ka kg ki kj kk kl km kn ko kr ks ku kv kw
  ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mo mr ms mt my na nb nd ne ng nl nn no nr nv
  ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss
  st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za
  zh zu
`
  .trim()
  .split(/\s+/);

// Codes ISO 639-1 has since left behind, each of which the browser's language data resolves
// onto another entry here: iw to he, in to id, ji to yi, mo to ro, and tw to ak. Offered as
// well, they would put a second "Hebrew" in the list with nothing to tell it from the first.
const SUPERSEDED = new Set(["in", "iw", "ji", "mo", "tw"]);

// Locales worth choosing between, because the content behind them differs rather than merely
// the spelling. Where any locale of a language is offered, its principal one is offered too, so
// that the group reads as a set rather than as exceptions.
const REGIONAL = [
  "en-US", "en-GB", "en-AU", "en-CA", "en-IN",
  "es-ES", "es-MX", "es-419",
  "pt-BR", "pt-PT",
  "fr-FR", "fr-CA",
  "de-DE", "de-AT", "de-CH",
  "nl-NL", "nl-BE",
  "zh-CN", "zh-TW", "zh-HK",
  "sr-Cyrl", "sr-Latn",
];

// "standard" names a locale as its language and place — "Portuguese (Brazil)" rather than
// "Brazilian Portuguese" — which keeps every locale of a language beside the language itself
// once the list is in alphabetical order.
const names = new Intl.DisplayNames(["en"], { type: "language", languageDisplay: "standard" });

/** Ordered by name, which is the order they are offered in. */
export const LANGUAGES: Language[] = [
  ...PRIMARY.filter((tag) => !SUPERSEDED.has(tag)),
  ...REGIONAL,
]
  .map((tag) => ({ tag, label: names.of(tag) ?? tag }))
  // Language data pared down to one locale answers with the tag it was given. A row reading
  // "ae" is the very thing this list exists to spare anyone, so it is left out; a setting that
  // asks for such a language is still edited as a header.
  .filter((language) => language.label !== language.tag)
  .sort((a, b) => a.label.localeCompare(b.label, "en"));

/** The Accept-Language header asking for a tag, with the bare language behind it. */
export function acceptLanguage(tag: string): string {
  const base = tag.split("-")[0]!;
  // A bare language has nothing to fall back to, and "sl,sl;q=0.9" says nothing twice.
  return base === tag ? tag : `${tag},${base};q=0.9`;
}

/** The listed language a header asks for, or null when it says something the list cannot. */
export function languageTag(header: string): string | null {
  return LANGUAGES.find((language) => acceptLanguage(language.tag) === header)?.tag ?? null;
}
