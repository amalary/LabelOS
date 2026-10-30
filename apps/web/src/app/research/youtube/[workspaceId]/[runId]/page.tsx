import { notFound } from "next/navigation";
import { AppShell } from "../../../../../components/app-shell";
import { YouTubeResearchPanel } from "../../../../../components/youtube-research-panel";
import { requireDashboardSession } from "../../../../../lib/dashboard-session";
import { researchPolicies } from "../../../../../lib/research-policy";

export default async function ResearchPage({
  params,
}: {
  params: Promise<{ workspaceId: string; runId: string }>;
}) {
  await requireDashboardSession();
  const { privacyUrl, termsUrl } = researchPolicies();
  if (!privacyUrl || !termsUrl) notFound();
  const { workspaceId, runId } = await params;
  return (
    <AppShell>
      <YouTubeResearchPanel
        key={`${workspaceId}:${runId}`}
        workspaceId={workspaceId}
        runId={runId}
        privacyUrl={privacyUrl}
        termsUrl={termsUrl}
      />
    </AppShell>
  );
}
