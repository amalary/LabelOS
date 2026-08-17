"use client";

import {
  type KeyboardEvent,
  useActionState,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import { Button, cn } from "@label-os/ui";

import { switchOrganization, type SwitchOrganizationState } from "../app/dashboard/actions";
import { clearOrganizationScopedBrowserCaches } from "../lib/browser-cache";
import type { OrganizationSummary } from "../lib/organizations";

type OrganizationSwitcherProps = {
  activeOrganization: OrganizationSummary | null;
  error?: string | null;
  isLoading?: boolean;
  organizations: OrganizationSummary[];
};

const initialState: SwitchOrganizationState = { error: null };

function roleLabel(role: OrganizationSummary["role"]) {
  return `${role.charAt(0).toUpperCase()}${role.slice(1)}`;
}

function organizationInitials(name: string) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");

  return initials || "LO";
}

function organizationLogoUrl(organization: OrganizationSummary) {
  return organization.logoUrl ?? organization.logo_url ?? null;
}

function OrganizationAvatar({
  organization,
  size = "md",
}: {
  organization: OrganizationSummary;
  size?: "sm" | "md";
}) {
  const logoUrl = organizationLogoUrl(organization);
  const sizeClass = size === "sm" ? "h-7 w-7 text-[0.65rem]" : "h-9 w-9 text-xs";

  if (logoUrl) {
    return (
      <span
        aria-label={`${organization.name} logo`}
        className={cn(
          "shrink-0 rounded-md bg-slate-100 bg-cover bg-center ring-1 ring-slate-200",
          sizeClass,
        )}
        role="img"
        style={{ backgroundImage: `url("${logoUrl}")` }}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md bg-slate-950 font-semibold text-white",
        sizeClass,
      )}
    >
      {organizationInitials(organization.name)}
    </span>
  );
}

export function OrganizationSwitcher({
  activeOrganization,
  error = null,
  isLoading = false,
  organizations,
}: OrganizationSwitcherProps) {
  const [state, formAction, pending] = useActionState(switchOrganization, initialState);
  const buttonId = useId();
  const listboxId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [selectedId, setSelectedId] = useState(
    activeOrganization?.id ?? organizations[0]?.id ?? "",
  );
  const previousActiveId = useRef(activeOrganization?.id ?? null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (previousActiveId.current !== activeOrganization?.id) {
      setSelectedId(activeOrganization?.id ?? organizations[0]?.id ?? "");
      previousActiveId.current = activeOrganization?.id ?? null;
    }
  }, [activeOrganization?.id, organizations]);

  const selectedOrganization = useMemo(
    () => organizations.find((organization) => organization.id === selectedId) ?? null,
    [organizations, selectedId],
  );
  const displayedOrganization = activeOrganization ?? selectedOrganization;
  const statusMessage = state.error ?? error;

  function focusOption(index: number) {
    optionRefs.current[index]?.focus();
  }

  function openMenu(nextIndex?: number) {
    setIsOpen(true);
    window.setTimeout(() => {
      const activeIndex = organizations.findIndex(
        (organization) => organization.id === (activeOrganization?.id ?? selectedId),
      );
      focusOption(nextIndex ?? Math.max(activeIndex, 0));
    }, 0);
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openMenu();
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      openMenu(organizations.length - 1);
    }
  }

  function onOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusOption((index + 1) % organizations.length);
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      focusOption((index - 1 + organizations.length) % organizations.length);
    }

    if (event.key === "Home") {
      event.preventDefault();
      focusOption(0);
    }

    if (event.key === "End") {
      event.preventDefault();
      focusOption(organizations.length - 1);
    }

    if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      document.getElementById(buttonId)?.focus();
    }
  }

  if (isLoading) {
    return (
      <div
        aria-label="Loading workspaces"
        className="flex h-11 min-w-0 max-w-[16rem] items-center gap-3 rounded-md border border-white/70 bg-white/60 px-3 shadow-sm"
        role="status"
      >
        <span className="h-8 w-8 animate-pulse rounded-md bg-slate-200" />
        <span className="min-w-0 flex-1">
          <span className="block h-3 w-28 animate-pulse rounded bg-slate-200" />
          <span className="mt-2 block h-2 w-16 animate-pulse rounded bg-slate-100" />
        </span>
      </div>
    );
  }

  if (organizations.length === 0) {
    return (
      <div
        aria-label="No workspaces available"
        className="flex h-11 min-w-0 max-w-[16rem] items-center rounded-md border border-dashed border-slate-300 bg-white/60 px-3 text-sm font-medium text-slate-600 shadow-sm"
        role="status"
      >
        No workspaces
      </div>
    );
  }

  return (
    <form action={formAction} className="relative min-w-0">
      <Button
        aria-controls={isOpen ? listboxId : undefined}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-labelledby={`${buttonId}-label ${buttonId}-name`}
        className="h-11 max-w-[min(16rem,calc(100vw-2rem))] justify-start gap-3 border-white/70 bg-white/70 px-3 text-left shadow-sm hover:bg-white focus-visible:outline-sky-500"
        disabled={pending}
        id={buttonId}
        onBlur={(event) => {
          if (!event.currentTarget.parentElement?.contains(event.relatedTarget)) {
            setIsOpen(false);
          }
        }}
        onClick={() => setIsOpen((current) => !current)}
        onKeyDown={onTriggerKeyDown}
        type="button"
        variant="secondary"
      >
        <span className="sr-only" id={`${buttonId}-label`}>
          Active organization
        </span>
        {displayedOrganization ? (
          <>
            <OrganizationAvatar organization={displayedOrganization} />
            <span className="min-w-0 flex-1">
              <span
                className="block truncate text-sm font-semibold text-slate-950"
                id={`${buttonId}-name`}
              >
                {displayedOrganization.name}
              </span>
              <span className="block truncate text-xs font-normal text-slate-500">
                {roleLabel(displayedOrganization.role)}
              </span>
            </span>
          </>
        ) : (
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-amber-900">
            Select workspace
          </span>
        )}
        <span aria-hidden="true" className="ml-auto text-xs text-slate-500">
          {pending ? "..." : "v"}
        </span>
      </Button>
      {isOpen ? (
        <div
          aria-labelledby={buttonId}
          className="absolute right-0 z-20 mt-2 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg"
          id={listboxId}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) {
              setIsOpen(false);
            }
          }}
          role="listbox"
        >
          {organizations.map((organization, index) => {
            const isActive = organization.id === activeOrganization?.id;
            const disabled = pending || isActive || !organization.can_switch;

            return (
              <button
                aria-disabled={disabled}
                aria-selected={isActive}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2 text-left transition focus-visible:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-sky-500",
                  isActive ? "bg-slate-50" : "hover:bg-slate-50",
                  disabled ? "cursor-not-allowed opacity-60" : "",
                )}
                key={organization.id}
                name="organizationId"
                onClick={(event) => {
                  if (disabled) {
                    event.preventDefault();
                    return;
                  }
                  setSelectedId(organization.id);
                  clearOrganizationScopedBrowserCaches();
                }}
                onKeyDown={(event) => onOptionKeyDown(event, index)}
                ref={(element) => {
                  optionRefs.current[index] = element;
                }}
                role="option"
                type="submit"
                value={organization.id}
              >
                <OrganizationAvatar organization={organization} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-slate-950">
                    {organization.name}
                  </span>
                  <span className="block truncate text-xs text-slate-500">
                    {isActive ? "Current workspace" : roleLabel(organization.role)}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
      {statusMessage ? (
        <p className="mt-2 max-w-[22rem] text-xs leading-5 text-rose-700" role="alert">
          {statusMessage}
        </p>
      ) : null}
      {!activeOrganization && organizations.length > 0 ? (
        <p className="mt-2 max-w-[22rem] text-xs leading-5 text-amber-700" role="status">
          Select an organization to continue.
        </p>
      ) : null}
    </form>
  );
}
