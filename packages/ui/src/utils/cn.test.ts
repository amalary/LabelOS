import { describe, expect, it } from "vitest";

import { cn } from "./cn";

describe("cn", () => {
  it("joins only truthy class names in order", () => {
    expect(cn("base", undefined, false, "custom")).toBe("base custom");
  });
});
