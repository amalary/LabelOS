import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { CampaignDetailWorkspace } from "./campaign-detail-workspace";

export default async function CampaignDetailPage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  await requireDashboardSession();
  const { campaignId } = await params;

  return (
    <AppShell>
      <CampaignDetailWorkspace campaignId={campaignId} />
    </AppShell>
  );
}
