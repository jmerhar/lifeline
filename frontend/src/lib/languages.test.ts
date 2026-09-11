import { describe, expect, it, vi } from "vitest";

import { acceptLanguage, LANGUAGES, languageTag } from "./languages";

describe("acceptLanguage", () => {
  it("puts the bare language behind a locale", () => {
    expect(acceptLanguage("pt-BR")).toBe("pt-BR,pt;q=0.9");
  });

  it("asks for a bare language as itself", () => {
    expect(acceptLanguage("sl")).toBe("sl");
  });

  it("keeps a script subtag in the locale it belongs to", () => {
    expect(acceptLanguage("sr-Latn")).toBe("sr-Latn,sr;q=0.9");
  });
});

describe("languageTag", () => {
  it("recognises a bare language", () => {
    expect(languageTag("hu")).toBe("hu");
  });

  it("tells apart two locales of one language", () => {
    expect(languageTag("pt-BR,pt;q=0.9")).toBe("pt-BR");
    expect(languageTag("pt-PT,pt;q=0.9")).toBe("pt-PT");
  });

  it("recognises the header an untouched installation starts with", () => {
    expect(languageTag("en-US,en;q=0.9")).toBe("en-US");
  });

  it("does not claim a header it cannot offer", () => {
    expect(languageTag("de-AT,de;q=0.8,en;q=0.5")).toBeNull();
  });

  it("does not claim a locale written without its fallback", () => {
    expect(languageTag("pt-BR")).toBeNull();
  });
});

describe("LANGUAGES", () => {
  it("covers every language ISO 639-1 names", () => {
    // 188 codes, less the five the language data resolves onto another entry.
    expect(LANGUAGES.filter((language) => !language.tag.includes("-"))).toHaveLength(183);
  });

  it("reaches well past the languages of Europe", () => {
    const labels = LANGUAGES.map((language) => language.label);
    expect(labels).toContain("Slovenian");
    expect(labels).toContain("Zulu");
    expect(labels).toContain("Nepali");
    expect(labels).toContain("Quechua");
    expect(labels).toContain("Swahili");
  });

  it("offers the locales of a language that is served by country", () => {
    const labels = LANGUAGES.map((language) => language.label);
    expect(labels).toContain("Portuguese");
    expect(labels).toContain("Portuguese (Brazil)");
    expect(labels).toContain("Portuguese (Portugal)");
  });

  it("leaves out the codes ISO 639-1 has replaced", () => {
    const tags = LANGUAGES.map((language) => language.tag);
    // Each would otherwise appear under the name of the language that replaced it.
    for (const superseded of ["in", "iw", "ji", "mo", "tw"]) {
      expect(tags).not.toContain(superseded);
    }
    for (const replacement of ["id", "he", "yi", "ro", "ak"]) {
      expect(tags).toContain(replacement);
    }
  });

  it("offers each tag once", () => {
    expect(new Set(LANGUAGES.map((language) => language.tag)).size).toBe(LANGUAGES.length);
  });

  it("names each language once", () => {
    expect(new Set(LANGUAGES.map((language) => language.label)).size).toBe(LANGUAGES.length);
  });

  it("names every language rather than showing its code", () => {
    for (const language of LANGUAGES) {
      expect(language.label).not.toBe(language.tag);
    }
  });

  it("is in the order it is offered in", () => {
    const labels = LANGUAGES.map((language) => language.label);
    expect(labels).toEqual([...labels].sort((a, b) => a.localeCompare(b, "en")));
  });

  it("leaves out a language the browser cannot name", async () => {
    // Language data pared down to one locale answers with the tag it was given — or with
    // nothing at all — and a row reading "ae" helps nobody either way.
    class Sparse {
      of(tag: string) {
        if (tag === "sl") return "Slovenian";
        return tag === "hu" ? undefined : tag;
      }
    }
    vi.stubGlobal("Intl", { ...Intl, DisplayNames: Sparse });
    vi.resetModules();

    const sparse = await import("./languages");
    expect(sparse.LANGUAGES).toEqual([{ tag: "sl", label: "Slovenian" }]);

    vi.unstubAllGlobals();
    vi.resetModules();
  });
});
