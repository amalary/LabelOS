import { describe, expect, it } from "vitest";

import { clearOrganizationScopedBrowserCaches } from "./browser-cache";

describe("browser cache cleanup", () => {
  it("clears only LabelOS session-scoped cache entries", () => {
    sessionStorage.setItem("labelos:artists:org-a", "cached");
    sessionStorage.setItem("labelos:dashboard:org-a", "cached");
    sessionStorage.setItem("unrelated", "keep");

    clearOrganizationScopedBrowserCaches();

    expect(sessionStorage.getItem("labelos:artists:org-a")).toBeNull();
    expect(sessionStorage.getItem("labelos:dashboard:org-a")).toBeNull();
    expect(sessionStorage.getItem("unrelated")).toBe("keep");
  });
});
