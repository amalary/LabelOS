import { expect, it } from "vitest";
import { researchPolicies } from "./research-policy";

const local = {
  APP_ENV: "local",
  YOUTUBE_RESEARCH_UI_ENABLED: "true",
  YOUTUBE_RESEARCH_USE_LOCAL_POLICIES: "true",
  LABELOS_POLICY_OPERATOR: "Test operator",
  LABELOS_PRIVACY_CONTACT: "privacy@example.test",
  LABELOS_RESEARCH_POLICIES_APPROVED: "true",
};
it("keeps draft or incomplete local policies from enabling discovery", () => {
  for (const key of [
    "LABELOS_POLICY_OPERATOR",
    "LABELOS_PRIVACY_CONTACT",
    "LABELOS_RESEARCH_POLICIES_APPROVED",
  ]) {
    expect(researchPolicies({ ...local, [key]: "" }).privacyUrl).toBeUndefined();
  }
  expect(
    researchPolicies({ ...local, YOUTUBE_RESEARCH_UI_ENABLED: "false" }).privacyUrl,
  ).toBeUndefined();
});
it("permits reviewed bundled documents only in the explicit local profile", () => {
  expect(researchPolicies(local)).toMatchObject({
    privacyUrl: "/privacy",
    termsUrl: "/terms",
    localSetup: true,
  });
  expect(researchPolicies({ ...local, APP_ENV: "production" }).privacyUrl).toBeUndefined();
  expect(researchPolicies({ ...local, APP_ENV: "staging" }).localSetup).toBe(false);
});
it("requires valid HTTPS external policy URLs", () => {
  for (const url of [
    "http://example.test/privacy",
    "https://",
    "https://user:password@example.test/privacy",
  ]) {
    expect(
      researchPolicies({
        YOUTUBE_RESEARCH_UI_ENABLED: "true",
        YOUTUBE_RESEARCH_PRIVACY_POLICY_URL: url,
      }).privacyUrl,
    ).toBeUndefined();
  }
});
