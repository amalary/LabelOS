/** Server-side configuration only. Never import into client components. */
export function researchPolicies(env: Record<string, string | undefined> = process.env) {
  const operator = env.LABELOS_POLICY_OPERATOR?.trim();
  const contact = env.LABELOS_PRIVACY_CONTACT?.trim();
  const approved =
    env.LABELOS_RESEARCH_POLICIES_APPROVED === "true" &&
    !!operator &&
    !!contact &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact);
  const local = env.APP_ENV === "local";
  const enabled = env.YOUTUBE_RESEARCH_UI_ENABLED === "true";
  const privacy = env.YOUTUBE_RESEARCH_PRIVACY_POLICY_URL;
  const terms = env.YOUTUBE_RESEARCH_TERMS_URL;
  function https(value: string | undefined) {
    try {
      const url = new URL(value ?? "");
      return url.protocol === "https:" && !url.username && !url.password;
    } catch {
      return false;
    }
  }
  // Relative bundled documents are allowed only in the explicit local profile,
  // after the operator has reviewed them. Public deployments still require HTTPS.
  const bundled = local && approved && env.YOUTUBE_RESEARCH_USE_LOCAL_POLICIES === "true";
  return {
    operator,
    contact,
    approved,
    localSetup: local,
    privacyUrl:
      enabled && (bundled || https(privacy)) ? (bundled ? "/privacy" : privacy) : undefined,
    termsUrl: enabled && (bundled || https(terms)) ? (bundled ? "/terms" : terms) : undefined,
  };
}
