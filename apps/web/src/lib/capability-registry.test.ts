import { describe, expect, it } from "vitest";

import {
  capabilities,
  capabilityKeys,
  capabilityRegistry,
  isValidCapabilityIdentifier,
  validateCapabilityIdentifier,
} from "./capability-registry";

describe("capability registry", () => {
  it("imports the central capability registry", () => {
    expect(capabilities.workspaceView).toBe("workspace.view");
    expect(capabilities.artistProfileEdit).toBe("artist.profile.edit");
    expect(capabilityRegistry.length).toBeGreaterThan(0);
  });

  it("keeps capability identifiers unique", () => {
    expect(new Set(capabilityKeys).size).toBe(capabilityKeys.length);
  });

  it("rejects malformed capability identifiers", () => {
    expect(isValidCapabilityIdentifier("workspace.view")).toBe(true);
    expect(isValidCapabilityIdentifier("workspace")).toBe(false);
    expect(isValidCapabilityIdentifier("Workspace.View")).toBe(false);
    expect(isValidCapabilityIdentifier("workspace:view")).toBe(false);
    expect(() => validateCapabilityIdentifier("workspace:view")).toThrow(
      "dot-separated lowercase segments",
    );
  });

  it("keeps future additions on the dot-separated resource.action pattern", () => {
    expect(capabilityKeys).toEqual(expect.arrayContaining(["release.approve"]));
    expect(capabilityKeys.every(isValidCapabilityIdentifier)).toBe(true);
    expect(capabilityKeys.every((key) => key.split(".").length >= 2)).toBe(true);
  });
});
