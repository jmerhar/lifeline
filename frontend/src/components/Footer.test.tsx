import { screen } from "@testing-library/react";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { describe, expect, it, vi } from "vitest";

import { render } from "../test/render";
import { server } from "../test/server";
import { Footer } from "./Footer";

const HEALTH = { status: "ok", database: "connected", version: "0.1.0" };

function answer(body: JsonBodyType) {
  server.use(http.get("/api/health", () => HttpResponse.json(body)));
}

describe("Footer", () => {
  it("names the version and links the commit the image was built from", async () => {
    answer({ ...HEALTH, revision: "0048894abcdef1234" });
    render(<Footer />);

    expect(await screen.findByText(/lifeline 0\.1\.0/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0048894" })).toHaveAttribute(
      "href",
      "https://github.com/jmerhar/lifeline/commit/0048894abcdef1234",
    );
  });

  it("shows only the version outside an image built by CI", async () => {
    answer({ ...HEALTH, revision: null });
    render(<Footer />);

    expect(await screen.findByText("lifeline 0.1.0")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("stays empty when the server cannot say", async () => {
    let asked = false;
    server.use(
      http.get("/api/health", () => {
        asked = true;
        return HttpResponse.json({ detail: "down" }, { status: 503 });
      }),
    );
    const { container } = render(<Footer />);

    await vi.waitFor(() => expect(asked).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.querySelector("footer")).toBeNull();
  });
});
