import Link from "next/link";
import { researchPolicies } from "../lib/research-policy";

export function ResearchPolicyDocument({ kind }: { kind: "privacy" | "terms" }) {
  const { operator, contact, approved } = researchPolicies();
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-6 py-12 text-slate-900">
      <nav className="flex gap-5" aria-label="Policy navigation">
        <Link href="/scouting">Scouting</Link>
        <Link href="/privacy">Privacy</Link>
        <Link href="/terms">Terms</Link>
      </nav>
      <h1 className="text-3xl font-semibold">
        LabelOS research {kind === "privacy" ? "privacy notice" : "terms of use"}
      </h1>
      {!approved && (
        <aside className="rounded border border-amber-300 bg-amber-50 p-4" role="note">
          Draft for operator review. This document is not yet active. Operator identity, contact
          details, deletion handling, and deployment practices must be confirmed before enabling
          research with these documents.
        </aside>
      )}
      <p>Document version: October 27, 2026. Scope: the local LabelOS A&amp;R research workflow.</p>
      <p>Operator: {operator || "Awaiting operator/company name"}.</p>
      <p>
        Privacy questions and deletion requests:{" "}
        {contact ? (
          <a className="underline" href={`mailto:${contact}`}>
            {contact}
          </a>
        ) : (
          "Awaiting a privacy contact"
        )}
        .
      </p>
      {kind === "privacy" ? <PrivacyText /> : <TermsText />}
    </main>
  );
}

function PrivacyText() {
  return (
    <>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Information used</h2>
        <p>
          LabelOS uses YouTube API Services to search public channels and display channel
          identifiers, titles, available country information, and current public counts. Search text
          is sent to Google when you submit a search. A channel identifier is sent when you request
          its current facts. Google also receives normal connection information from the LabelOS
          server. See the{" "}
          <a className="underline" href="https://policies.google.com/privacy">
            Google Privacy Policy
          </a>
          .
        </p>
        <p>
          Your account identity, workspace membership, and permissions determine access. WorkOS
          processes sign-in information and uses an authentication session cookie. LabelOS stores
          labels, notes, and review statuses you enter, plus the saved channel reference. Avoid
          entering unnecessary personal or sensitive information.
        </p>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Purpose and sharing</h2>
        <p>
          This information supports human-led artist research, workspace shortlists, and team
          review. Reviews are visible to authorized members of the same workspace. Operators may
          access information to support the service, investigate faults, secure accounts, and handle
          deletion requests.
        </p>
        <p>
          WorkOS provides authentication, and Google provides YouTube API Services and credential
          storage. In this local workflow, the application database runs on the operator&apos;s
          computer. Research does not send your human notes to YouTube, sell them, use them for
          advertising, or submit them to an AI model. This feature does not embed a YouTube player;
          opening a source link takes you to YouTube.
        </p>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Storage and retention</h2>
        <p>
          Channel titles and counts are displayed temporarily rather than saved as a history. Server
          display caches last at most 60 seconds; the browser removes displayed provider data after
          15 minutes. These responses use no-store caching. A saved channel reference expires after
          29 days; reads hide it immediately at expiry and the running API periodically erases
          expired references.
        </p>
        <p>
          Human labels, notes, and review statuses remain until deleted. Removing a channel
          reference keeps the human review. Deleting the candidate removes both. Operational records
          include request status, timings, account/workspace identifiers, and governance events;
          research does not deliberately log query text, titles, counts, credentials, or raw
          provider responses.
        </p>
        <p>
          The operator is responsible for retention and deletion of operational logs and any copies
          or backups. Visible expiry alone does not erase an offline database or a backup. Shared
          hosting requires an updated notice describing its providers, location, retention, and
          recovery practices.
        </p>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Control and deletion</h2>
        <p>
          Use Clear YouTube display data to clear the current view, Remove saved YouTube reference
          to unlink a candidate, or Delete candidate and notes to remove its review. These actions
          affect LabelOS data only. They do not delete a YouTube channel, video, or data held by
          Google.
        </p>
        <p>
          Contact the operator above to request access, correction, account deletion, or deletion of
          stored information related to you. Include enough information to identify the account or
          channel, but never send passwords or API keys. The operator verifies the request and its
          scope and handles applicable YouTube-data deletion promptly and within seven calendar
          days, including retained copies.
        </p>
        <p>
          Public-channel research does not connect your YouTube account or request its password.
          Separately authorized Google applications can be managed in your
          <a className="underline" href="https://security.google.com/settings/security/permissions">
            {" "}
            Google security settings
          </a>
          . The separate LabelOS publishing workflow is outside this notice.
        </p>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Changes</h2>
        <p>
          The operator will update this notice if the research workflow changes. Material changes to
          collection or use require renewed agreement before that use begins.
        </p>
      </section>
    </>
  );
}

function TermsText() {
  return (
    <>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Using research</h2>
        <p>
          LabelOS research helps authorized workspace members inspect public YouTube channels and
          record their own reviews. By using its YouTube features, you agree to be bound by the{" "}
          <a className="underline" href="https://www.youtube.com/t/terms">
            YouTube Terms of Service
          </a>{" "}
          and these research terms. Read and agree to the{" "}
          <Link className="underline" href="/privacy">
            privacy notice
          </Link>{" "}
          before making research requests.
        </p>
        <p>
          Use only workspaces you are authorized to access. Keep account credentials private. Do not
          circumvent access controls or quota limits, scrape or bulk-export YouTube data, download
          media through this feature, or use it to build derived scores, cross-owner metrics, or an
          unapproved history of provider statistics.
        </p>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Data and human review</h2>
        <p>
          Public channels are research candidates, not verified artist identities or endorsements.
          Counts can be rounded, hidden, unavailable, stale, or removed. Check the original YouTube
          source and refresh before relying on a fact. Your labels, notes, and review statuses are
          human judgments, not information supplied or endorsed by YouTube. You retain
          responsibility for what you enter and share.
        </p>
        <p>
          Saving a candidate does not grant rights to its name, music, videos, or other content. Do
          not store copied provider payloads in notes to avoid retention rules. Saved references
          expire; saving the channel again after removal may create a separate review. The local
          service may be unavailable or change during testing.
        </p>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Requests and changes</h2>
        <p>
          Use the privacy contact above for questions, corrections, or deletion requests. The
          operator may restrict access to protect accounts, enforce these terms, or meet provider
          requirements. These terms cover local research only; shared or production use requires a
          review of the actual service and its policies.
        </p>
      </section>
    </>
  );
}
