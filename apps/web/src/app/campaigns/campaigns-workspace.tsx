"use client";

import { Badge, Button, Card, EmptyState, Input, LoadingState, PageHeader, cn } from "@label-os/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { can, capabilities } from "../../lib/authorization";
import {
  type Campaign,
  type CampaignCreate,
  useCampaigns,
  useCreateCampaign,
} from "../../lib/campaigns";
import { useWorkspacePeopleDirectory } from "../../lib/profiles";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type CampaignFormState = {
  name: string;
  description: string;
  campaign_type: string;
  status: string;
  start_date: string;
  target_end_date: string;
  owner_profile_id: string;
};

const initialForm: CampaignFormState = {
  name: "",
  description: "",
  campaign_type: "marketing",
  status: "draft",
  start_date: "",
  target_end_date: "",
  owner_profile_id: "",
};

const campaignTypeOptions = [
  { value: "marketing", label: "Marketing" },
  { value: "release", label: "Release" },
  { value: "artist_development", label: "Artist development" },
  { value: "catalog", label: "Catalog" },
  { value: "other", label: "Other" },
];

const campaignPageSize = 50;

const statusOptions = [
  { value: "draft", label: "Draft" },
  { value: "planning", label: "Planning" },
  { value: "active", label: "Active" },
];

function humanize(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string | null): string {
  if (!value) {
    return "No target";
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(`${value}T00:00:00`),
  );
}

function statusVariant(status: string) {
  if (status === "active" || status === "completed") {
    return "success" as const;
  }
  if (status === "planning" || status === "draft") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function milestoneSummary(campaign: Campaign): { label: string; percent: number } {
  const memberCount = campaign.members.length;
  const relationshipCount = campaign.artists.length + campaign.releases.length;
  const percent = Math.min(100, 25 + memberCount * 15 + relationshipCount * 15);
  const label =
    memberCount === 0 && relationshipCount === 0
      ? "Setup started"
      : `${memberCount} team member${memberCount === 1 ? "" : "s"}, ${relationshipCount} linked item${
          relationshipCount === 1 ? "" : "s"
        }`;
  return { label, percent };
}

function CampaignCreateForm({
  canCreate,
  onCreated,
}: {
  canCreate: boolean;
  onCreated: (campaign: Campaign) => void;
}) {
  const { activeWorkspace } = useActiveWorkspace();
  const people = useWorkspacePeopleDirectory(activeWorkspace?.id ?? null, { limit: 100 });
  const createCampaign = useCreateCampaign(activeWorkspace?.id ?? null);
  const [form, setForm] = useState<CampaignFormState>(initialForm);
  const [formError, setFormError] = useState<string | null>(null);

  const owners = people.data?.people ?? [];

  const updateForm = (field: keyof CampaignFormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canCreate) {
      return;
    }
    const name = form.name.trim();
    if (!name) {
      setFormError("Campaign name is required.");
      return;
    }
    const payload: CampaignCreate = {
      name,
      campaign_type: form.campaign_type,
      status: form.status,
      description: form.description.trim() || null,
      start_date: form.start_date || null,
      target_end_date: form.target_end_date || null,
      owner_profile_id: form.owner_profile_id || null,
    };
    setFormError(null);
    try {
      const campaign = await createCampaign.mutate(payload);
      setForm(initialForm);
      onCreated(campaign);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Campaign could not be created.");
    }
  };

  return (
    <Card>
      <form className="grid gap-4" onSubmit={submit}>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Create campaign</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              Start the shared workspace record. Department plans attach later.
            </p>
          </div>
          <Button disabled={!canCreate || createCampaign.isMutating} type="submit">
            {createCampaign.isMutating ? "Creating" : "Create campaign"}
          </Button>
        </div>

        {!canCreate ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            You can view campaigns, but campaign creation requires campaign create access.
          </div>
        ) : null}
        {formError ? (
          <div
            className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
            role="alert"
          >
            {formError}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Name
            <Input
              disabled={!canCreate || createCampaign.isMutating}
              onChange={(event) => updateForm("name", event.target.value)}
              placeholder="Single launch, catalog push, tour announcement"
              value={form.name}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Type
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
              disabled={!canCreate || createCampaign.isMutating}
              onChange={(event) => updateForm("campaign_type", event.target.value)}
              value={form.campaign_type}
            >
              {campaignTypeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Status
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
              disabled={!canCreate || createCampaign.isMutating}
              onChange={(event) => updateForm("status", event.target.value)}
              value={form.status}
            >
              {statusOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Owner
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
              disabled={!canCreate || createCampaign.isMutating || people.isLoading}
              onChange={(event) => updateForm("owner_profile_id", event.target.value)}
              value={form.owner_profile_id}
            >
              <option value="">Unassigned</option>
              {owners.map((person) => (
                <option key={person.profile_id} value={person.profile_id}>
                  {person.display_name ?? "Unnamed profile"}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Start date
            <Input
              disabled={!canCreate || createCampaign.isMutating}
              onChange={(event) => updateForm("start_date", event.target.value)}
              type="date"
              value={form.start_date}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Target date
            <Input
              disabled={!canCreate || createCampaign.isMutating}
              onChange={(event) => updateForm("target_end_date", event.target.value)}
              type="date"
              value={form.target_end_date}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700 md:col-span-2">
            Description
            <textarea
              className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-950 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
              disabled={!canCreate || createCampaign.isMutating}
              onChange={(event) => updateForm("description", event.target.value)}
              placeholder="Campaign purpose, audience, launch window, or operating notes"
              value={form.description}
            />
          </label>
        </div>
      </form>
    </Card>
  );
}

function CampaignListItem({ campaign }: { campaign: Campaign }) {
  const progress = milestoneSummary(campaign);

  return (
    <Link
      className="block transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-slate-700"
      href={`/campaigns/${campaign.id}`}
    >
      <article className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(160px,0.7fr)_minmax(180px,0.8fr)_minmax(180px,0.9fr)] lg:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold text-slate-950">{campaign.name}</h2>
            <Badge variant={statusVariant(campaign.status)}>{humanize(campaign.status)}</Badge>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            {humanize(campaign.campaign_type)} -{" "}
            {campaign.primary_artist?.name ?? "No primary artist"}
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Target</p>
          <p className="mt-1 text-sm font-medium text-slate-800">
            {formatDate(campaign.target_end_date)}
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Owner</p>
          <p className="mt-1 truncate text-sm font-medium text-slate-800">
            {campaign.owner?.display_name ?? "Unassigned"}
          </p>
        </div>
        <div>
          <div className="flex items-center justify-between gap-3">
            <p className="truncate text-xs font-semibold uppercase tracking-normal text-slate-500">
              Milestones
            </p>
            <p className="text-xs font-medium text-slate-500">{progress.percent}%</p>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-slate-950"
              style={{ width: `${progress.percent}%` }}
            />
          </div>
          <p className="mt-1 truncate text-xs text-slate-500">{progress.label}</p>
        </div>
      </article>
    </Link>
  );
}

export function CampaignsWorkspace() {
  const router = useRouter();
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const [campaignLimit, setCampaignLimit] = useState(campaignPageSize);
  const campaigns = useCampaigns(activeWorkspace?.id ?? null, {
    limit: campaignLimit,
    offset: 0,
  });
  const [showCreate, setShowCreate] = useState(false);
  const canView = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.marketingCampaignView)
    : false;
  const canCreate = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.marketingCampaignCreate)
    : false;
  const visibleCampaigns = useMemo(() => campaigns.data?.campaigns ?? [], [campaigns.data]);
  const totalCampaigns = campaigns.data?.total ?? visibleCampaigns.length;
  const canLoadMore = visibleCampaigns.length < totalCampaigns;

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view campaigns.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        actions={
          <Button disabled={!canCreate} onClick={() => setShowCreate((current) => !current)}>
            {showCreate ? "Close" : "New campaign"}
          </Button>
        }
        description={`${activeWorkspace.name} campaign planning, ownership, and launch coordination.`}
        eyebrow="Campaign Workspace"
        title="Campaigns"
      />

      {!canView && !workspaceProfile.isLoading ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          You need campaign view access to open this workspace.
        </div>
      ) : null}

      {showCreate ? (
        <CampaignCreateForm
          canCreate={canCreate}
          onCreated={(campaign) => router.push(`/campaigns/${campaign.id}`)}
        />
      ) : null}

      {campaigns.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          Campaigns could not be loaded.
        </div>
      ) : null}

      {campaigns.isLoading && !campaigns.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading campaigns" />
          {Array.from({ length: 4 }, (_, index) => (
            <div className="h-20 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : visibleCampaigns.length === 0 ? (
        <EmptyState
          action={
            canCreate ? (
              <Button onClick={() => setShowCreate(true)} variant="secondary">
                Create campaign
              </Button>
            ) : null
          }
          description={
            canCreate
              ? "Create the first campaign record for this workspace."
              : "Campaign records appear here when someone with campaign create access adds them."
          }
          title="No campaigns yet"
        />
      ) : (
        <Card className={cn("overflow-hidden p-0", campaigns.isLoading ? "opacity-80" : "")}>
          <div className="flex flex-col gap-2 border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700 sm:flex-row sm:items-center sm:justify-between">
            <span>
              Showing {visibleCampaigns.length} of {totalCampaigns} campaign
              {totalCampaigns === 1 ? "" : "s"}
            </span>
            {canLoadMore ? (
              <Button
                disabled={campaigns.isLoading}
                onClick={() => setCampaignLimit((current) => current + campaignPageSize)}
                size="sm"
                variant="secondary"
              >
                Load more
              </Button>
            ) : null}
          </div>
          <div className="divide-y divide-slate-100">
            {visibleCampaigns.map((campaign) => (
              <CampaignListItem campaign={campaign} key={campaign.id} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
