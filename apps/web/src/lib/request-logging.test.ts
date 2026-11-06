import { expect, it } from "vitest";
import config from "../../next.config";

it("suppresses credential-bearing development request URLs", () => {
  const logging = config.logging;
  if (!logging || typeof logging.incomingRequests !== "object")
    throw new Error("Missing request privacy rules");
  const ignored = (url: string) =>
    logging.incomingRequests &&
    typeof logging.incomingRequests === "object" &&
    logging.incomingRequests.ignore?.some((pattern) => pattern.test(url));
  for (const url of [
    "/api/auth/callback?code=PRIVATE",
    "/join/PRIVATE",
    "/api/organizations/invites/PRIVATE/accept",
    "/api/social-account-connections/oauth/youtube/callback?code=PRIVATE",
  ]) {
    expect(ignored(url)).toBe(true);
  }
  expect(ignored("/scouting")).toBe(false);
});
