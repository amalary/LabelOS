import { describe, expect, it } from "vitest";
import { publicProviderUrl, publicationFailureMessage } from "./publications";

describe("public publication evidence", () => {
  it.each([
    "javascript:alert(1)",
    "http://provider.example/post",
    "https://user:secret@provider.example/post",
    "https://provider.example/post?token=secret",
    "https://provider.example/post#secret",
    "https://provider.example:444/post",
    "https://provider.example\\post",
    "https://provider.example/\npost",
  ])("rejects unsafe links: %s", (value) => {
    expect(publicProviderUrl(value)).toBeNull();
  });
  it("accepts public HTTPS resource links", () => {
    expect(publicProviderUrl("https://www.youtube.com/shorts/video-id")).toBe(
      "https://www.youtube.com/shorts/video-id",
    );
  });
  it("never reflects unknown normalized error codes", () => {
    expect(publicationFailureMessage("Authorization: Bearer private")).not.toContain("private");
    expect(publicationFailureMessage("rate_limited")).toContain("rate limit");
  });
});
