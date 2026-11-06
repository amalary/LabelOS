"use client";

import { useMarketingCalendar } from "./use-marketing-calendar";

import { Button, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { can, capabilities } from "../../lib/authorization";
import {
  addCalendarMonths,
  currentCalendarMonthDate,
  formatCalendarDateTime,
  formatCalendarMonthTitle,
} from "../../lib/calendar-dates";
import { useCampaigns } from "../../lib/campaigns";
import { type MarketingContentItem } from "../../lib/marketing-content";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";
import { ApprovalQueue } from "./approval-queue";
import { ContentEditorDetail } from "./content-editor";
import { type ContentEditorSurface } from "./content-form";
import { DraftsTab } from "./drafts-tab";
import { CalendarList, type CalendarView, Filters, MonthCalendar } from "./marketing-calendar";
import {
  type CalendarFilters,
  filtersActive,
  planningFallbackTimeZone,
} from "./marketing-presentation";
import { SocialAccountsTab } from "./social-accounts-tab";

type MarketingTab = "calendar" | "drafts" | "approvals" | "accounts";

const tabs: Array<{ id: MarketingTab; label: string; enabled: boolean }> = [
  { id: "calendar", label: "Calendar", enabled: true },
  { id: "drafts", label: "Drafts", enabled: true },
  { id: "approvals", label: "Approvals", enabled: true },
  { id: "accounts", label: "Accounts", enabled: true },
];

export function MarketingWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const tabParam = searchParams.get("tab");
  const initialTab: MarketingTab =
    tabParam === "accounts" || tabParam === "approvals" || tabParam === "drafts"
      ? tabParam
      : "calendar";
  const [activeTab, setActiveTab] = useState<MarketingTab>(initialTab);
  const [view, setView] = useState<CalendarView>("month");
  const initialCampaignId = searchParams.get("campaignId") ?? "";
  const createDate = searchParams.get("createDate");
  const timeZone =
    workspaceProfile.membership?.profile.preferences.timezone ??
    workspaceProfile.membership?.profile.timezone ??
    planningFallbackTimeZone;
  const [filters, setFilters] = useState<CalendarFilters>({
    artistId: "",
    campaignId: initialCampaignId,
    channel: "",
    releaseId: "",
    status: "",
  });
  const [monthDate, setMonthDate] = useState(() => currentCalendarMonthDate(timeZone));
  const [editor, setEditor] = useState<
    | {
        key: string;
        mode: "create";
        item: null;
        createDate: string | null;
        surface: ContentEditorSurface;
      }
    | {
        key: string;
        mode: "edit";
        item: MarketingContentItem;
        createDate: null;
        surface: ContentEditorSurface;
      }
    | null
  >(() =>
    createDate
      ? {
          createDate,
          item: null,
          key: `create:${createDate}`,
          mode: "create",
          surface: "calendar",
        }
      : null,
  );
  const [savedRevision, setSavedRevision] = useState(0);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [focusedApprovalId, setFocusedApprovalId] = useState<string | null>(
    searchParams.get("approvalRequestId"),
  );

  const { range, calendarContent, items, scheduleInstances, currentMonthDays, instancesByDay } =
    useMarketingCalendar(activeWorkspace?.id ?? null, filters, monthDate, timeZone);
  const campaigns = useCampaigns(activeWorkspace?.id ?? null, { limit: 500, offset: 0 });
  const canView =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentView)
      : false;
  const canCreate =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentCreate)
      : false;
  const canEdit =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentEdit)
      : false;
  const canArchive =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentArchive)
      : false;
  const canSubmitForReview =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentSubmitForReview)
      : false;
  const canViewAccounts =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingAccountView)
      : false;
  const canManageAccounts =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingAccountManage)
      : false;

  const updateUrl = useCallback(
    (nextFilters: CalendarFilters, createDate?: string) => {
      const next = new URLSearchParams(searchParams.toString());
      if (nextFilters.campaignId) {
        next.set("campaignId", nextFilters.campaignId);
      } else {
        next.delete("campaignId");
      }
      if (createDate) {
        next.set("createDate", createDate);
      } else {
        next.delete("createDate");
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const openCreateEditor = useCallback(
    (dateKey: string | null = null, surface: ContentEditorSurface = "calendar") => {
      setSaveNotice(null);
      setEditor({
        createDate: dateKey,
        item: null,
        key: `create:${surface}:${dateKey ?? "blank"}:${Date.now()}`,
        mode: "create",
        surface,
      });
      updateUrl(filters, dateKey ?? undefined);
    },
    [filters, updateUrl],
  );

  const openEditEditor = useCallback(
    (selectedItem: MarketingContentItem, surface: ContentEditorSurface) => {
      setSaveNotice(null);
      setEditor({
        createDate: null,
        item: selectedItem,
        key: `edit:${surface}:${selectedItem.id}:${selectedItem.updated_at}`,
        mode: "edit",
        surface,
      });
    },
    [],
  );

  const closeEditor = useCallback(() => {
    setEditor(null);
    setSaveNotice(null);
    updateUrl(filters);
  }, [filters, updateUrl]);

  const handleSaved = useCallback(
    (savedItem: MarketingContentItem | null) => {
      setEditor(null);
      updateUrl(filters);
      setSaveNotice(
        savedItem
          ? `Saved ${savedItem.title}. Revision ${savedItem.content_revision}.`
          : "Marketing content updated.",
      );
      setSavedRevision((current) => current + 1);
      void calendarContent.reload().catch(() => undefined);
    },
    [calendarContent, filters, updateUrl],
  );
  const handleArchived = useCallback(
    (archivedItem: MarketingContentItem) => {
      setEditor(null);
      updateUrl(filters);
      setSaveNotice(`Archived ${archivedItem.title}.`);
      setSavedRevision((current) => current + 1);
      void calendarContent.reload().catch(() => undefined);
    },
    [calendarContent, filters, updateUrl],
  );

  const updateFilters = useCallback(
    (next: Partial<CalendarFilters>) => {
      setFilters((current) => {
        const merged = { ...current, ...next };
        updateUrl(merged);
        return merged;
      });
    },
    [updateUrl],
  );

  const resetFilters = useCallback(() => {
    const next = { artistId: "", campaignId: "", channel: "", releaseId: "", status: "" };
    setFilters(next);
    updateUrl(next);
  }, [updateUrl]);

  const moveMonth = useCallback((amount: number) => {
    setMonthDate((current) => addCalendarMonths(current, amount));
  }, []);

  const showNoResults = items.length === 0 && filtersActive(filters);
  const campaignList = campaigns.data?.campaigns ?? [];

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view the Marketing Hub.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        description={`${activeWorkspace.name} content planning, approvals, and channel coordination.`}
        eyebrow="Phase 2 Marketing Hub"
        title="Marketing"
      />

      <nav aria-label="Marketing Hub sections" className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            aria-current={activeTab === tab.id ? "page" : undefined}
            className={cn(
              "rounded-md border px-3 py-2 text-sm font-medium transition",
              activeTab === tab.id
                ? "border-slate-950 bg-slate-950 text-white"
                : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
            )}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            <span>{tab.label}</span>
            {!tab.enabled ? (
              <>
                {" "}
                <span className="ml-2 text-xs font-normal opacity-75">Upcoming</span>
              </>
            ) : null}
          </button>
        ))}
      </nav>

      {!canView && activeTab !== "accounts" && !workspaceProfile.isLoading ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You need marketing content view access to open the Marketing Hub.
        </div>
      ) : null}

      {activeTab === "accounts" && !canViewAccounts && !workspaceProfile.isLoading ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You need marketing account view access to open Social Account Connections.
        </div>
      ) : null}

      {saveNotice ? (
        <div
          className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
          role="status"
        >
          {saveNotice}
        </div>
      ) : null}

      {activeTab === "calendar" && canView ? (
        <section className="grid gap-4" aria-label="Marketing content calendar">
          <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">
                {formatCalendarMonthTitle(monthDate)}
              </h2>
              <p className="text-sm text-slate-500">
                Showing {formatCalendarDateTime(range.start, timeZone)} through{" "}
                {formatCalendarDateTime(range.end, timeZone)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => moveMonth(-1)} size="sm" type="button" variant="secondary">
                Previous
              </Button>
              <Button
                onClick={() => {
                  setMonthDate(currentCalendarMonthDate(timeZone));
                }}
                size="sm"
                type="button"
                variant="secondary"
              >
                Today
              </Button>
              <Button onClick={() => moveMonth(1)} size="sm" type="button" variant="secondary">
                Next
              </Button>
              {canCreate ? (
                <Button onClick={() => openCreateEditor()} size="sm" type="button">
                  Create Content
                </Button>
              ) : null}
              <div className="ml-0 flex rounded-md border border-slate-300 p-0.5 md:ml-2">
                <button
                  aria-pressed={view === "month"}
                  className={cn(
                    "h-8 rounded px-3 text-sm font-medium",
                    view === "month" ? "bg-slate-950 text-white" : "text-slate-700",
                  )}
                  onClick={() => setView("month")}
                  type="button"
                >
                  Month
                </button>
                <button
                  aria-pressed={view === "list"}
                  className={cn(
                    "h-8 rounded px-3 text-sm font-medium",
                    view === "list" ? "bg-slate-950 text-white" : "text-slate-700",
                  )}
                  onClick={() => setView("list")}
                  type="button"
                >
                  List
                </button>
              </div>
            </div>
          </div>

          <Filters
            campaigns={campaignList}
            filters={filters}
            isLoadingCampaigns={campaigns.isLoading}
            onChange={updateFilters}
            onReset={resetFilters}
          />

          {editor ? (
            <ContentEditorDetail
              campaigns={campaignList}
              canEdit={canEdit}
              canArchive={canArchive}
              canSubmitForReview={canSubmitForReview}
              createDate={editor.createDate}
              filters={filters}
              item={editor.item}
              key={editor.key}
              mode={editor.mode}
              onCancel={closeEditor}
              onArchived={handleArchived}
              onOpenApprovalReview={(approvalRequestId) => {
                setFocusedApprovalId(approvalRequestId);
                setActiveTab("approvals");
                setEditor(null);
              }}
              onSaved={handleSaved}
              surface={editor.surface}
              timeZone={timeZone}
            />
          ) : null}

          {calendarContent.error ? (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
              role="alert"
            >
              {calendarContent.error.code === "forbidden"
                ? "Marketing content access was denied for these filters."
                : "Marketing content could not be loaded."}
            </div>
          ) : null}

          {calendarContent.isLoading && !calendarContent.data ? (
            <Card className="grid gap-3">
              <LoadingState label="Loading marketing calendar" />
              {Array.from({ length: 3 }, (_, index) => (
                <div className="h-16 rounded-md bg-slate-100 auth-shimmer" key={index} />
              ))}
            </Card>
          ) : items.length === 0 ? (
            <EmptyState
              description={
                showNoResults
                  ? "Try changing the campaign, status, channel, artist, release, or month."
                  : "Calendar content appears here after campaign content is scheduled."
              }
              title={showNoResults ? "No content matches these filters" : "No scheduled content"}
            />
          ) : view === "month" ? (
            <MonthCalendar
              campaigns={campaignList}
              days={currentMonthDays}
              instancesByDay={instancesByDay}
              onEmptyDayClick={(dateKey) => {
                if (canCreate) {
                  openCreateEditor(dateKey);
                } else {
                  updateUrl(filters, dateKey);
                }
              }}
              onItemClick={(selectedItem) => openEditEditor(selectedItem, "calendar")}
              timeZone={timeZone}
            />
          ) : (
            <CalendarList
              campaigns={campaignList}
              instances={scheduleInstances}
              onItemClick={(selectedItem) => openEditEditor(selectedItem, "calendar")}
              timeZone={timeZone}
            />
          )}
        </section>
      ) : null}

      {activeTab === "approvals" && canView ? (
        <ApprovalQueue
          currentProfileId={workspaceProfile.membership?.profile.id}
          focusedApprovalId={focusedApprovalId}
          onOpenCalendarItem={(contentItemId, campaignId) => {
            const nextFilters = {
              ...filters,
              campaignId: campaignId ?? filters.campaignId,
            };
            setFocusedApprovalId(null);
            setFilters(nextFilters);
            updateUrl(nextFilters);
            setActiveTab("calendar");
            const selectedItem = items.find((entry) => entry.id === contentItemId);
            if (selectedItem) {
              openEditEditor(selectedItem, "calendar");
            }
          }}
          timeZone={timeZone}
          workspaceId={activeWorkspace.id}
        />
      ) : null}

      {activeTab === "drafts" && canView ? (
        <>
          <DraftsTab
            canCreate={canCreate}
            canArchive={canArchive}
            canSubmitForReview={canSubmitForReview}
            campaigns={campaignList}
            onCreate={() => openCreateEditor(null, "drafts")}
            onArchived={handleArchived}
            onItemClick={(selectedItem) => openEditEditor(selectedItem, "drafts")}
            savedRevision={savedRevision}
            workspaceId={activeWorkspace.id}
          />
          {editor ? (
            <ContentEditorDetail
              campaigns={campaignList}
              canEdit={canEdit}
              canArchive={canArchive}
              canSubmitForReview={canSubmitForReview}
              createDate={editor.createDate}
              filters={filters}
              item={editor.item}
              key={editor.key}
              mode={editor.mode}
              onCancel={closeEditor}
              onArchived={handleArchived}
              onOpenApprovalReview={(approvalRequestId) => {
                setFocusedApprovalId(approvalRequestId);
                setActiveTab("approvals");
                setEditor(null);
              }}
              onSaved={handleSaved}
              surface={editor.surface}
              timeZone={timeZone}
            />
          ) : null}
        </>
      ) : null}

      {activeTab === "accounts" && canViewAccounts ? (
        <SocialAccountsTab
          campaigns={campaignList}
          canManage={canManageAccounts}
          workspaceId={activeWorkspace.id}
        />
      ) : null}
    </div>
  );
}

export {
  toScheduleInstance,
  toScheduleInstances,
  type MarketingScheduleInstance,
} from "./marketing-schedule";
