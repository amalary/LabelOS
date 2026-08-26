import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { ArtistProfileEditor } from "./artist-profile-editor";

export default async function ArtistProfileDetailPage({
  params,
}: {
  params: Promise<{ artistProfileId: string }>;
}) {
  await requireDashboardSession();
  const { artistProfileId } = await params;

  return (
    <AppShell>
      <ArtistProfileEditor artistProfileId={artistProfileId} />
    </AppShell>
  );
}
