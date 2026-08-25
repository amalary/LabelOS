import Link from "next/link";
import { cn } from "@label-os/ui";
import type { ReactNode } from "react";

import { DashboardPanel } from "./dashboard-panel";
import type { DashboardKpiTrendDirection } from "./dashboard.types";

export type KpiCardProps = {
  title: string;
  primaryValue?: string;
  value?: string;
  icon: ReactNode;
  trendValue?: string;
  trendDirection?: DashboardKpiTrendDirection;
  comparisonLabel?: string;
  description?: string;
  href?: string;
  actionLabel?: string;
  loading?: boolean;
  empty?: boolean;
  error?: string;
};

const trendToneClasses: Record<DashboardKpiTrendDirection, string> = {
  negative: "border-amber-300/20 bg-amber-300/10 text-amber-100",
  neutral: "border-slate-500/20 bg-slate-500/10 text-slate-200",
  positive: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
};

const trendLabels: Record<DashboardKpiTrendDirection, string> = {
  negative: "Decrease",
  neutral: "No change",
  positive: "Increase",
};

const trendSymbols: Record<DashboardKpiTrendDirection, string> = {
  negative: "\u2193",
  neutral: "\u2192",
  positive: "\u2191",
};

function kpiHeadingId(title: string) {
  return `${title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}-kpi-title`;
}

function KpiCardFrame({
  children,
  className,
  href,
  title,
}: {
  children: ReactNode;
  className?: string;
  href?: string;
  title: string;
}) {
  const panel = (
    <DashboardPanel
      aria-label={title}
      className={cn(
        "relative min-h-[8.5rem] overflow-hidden",
        href ? "dashboard-panel-interactive focus-within:border-cyan-300/50" : null,
        className,
      )}
    >
      <div
        className="absolute inset-x-5 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/40 to-transparent"
        aria-hidden="true"
      />
      {children}
    </DashboardPanel>
  );

  if (!href) {
    return panel;
  }

  return (
    <Link
      aria-label={`${title} details`}
      className="block rounded-[16px] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
      href={href}
    >
      {panel}
    </Link>
  );
}

function KpiTrend({
  comparisonLabel,
  trendDirection,
  trendValue,
}: Pick<KpiCardProps, "comparisonLabel" | "trendDirection" | "trendValue">) {
  if (!trendValue || !trendDirection) {
    return (
      <p className="text-sm font-medium text-slate-400" aria-label="No trend data">
        No trend data
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className={cn(
          "inline-flex items-center rounded-full border px-2 py-1 text-xs font-semibold",
          trendToneClasses[trendDirection],
        )}
        aria-label={`${trendLabels[trendDirection]} ${trendValue}`}
      >
        <span aria-hidden="true">{trendSymbols[trendDirection]}</span>{" "}
        <span>{trendLabels[trendDirection]}</span> <span>{trendValue}</span>
      </span>
      {comparisonLabel ? <span className="text-sm text-slate-400">{comparisonLabel}</span> : null}
    </div>
  );
}

export function KpiCard({
  actionLabel,
  comparisonLabel,
  description,
  empty = false,
  error,
  href,
  icon,
  loading = false,
  title,
  trendDirection,
  trendValue,
  primaryValue,
  value,
}: KpiCardProps) {
  const displayValue = primaryValue ?? value ?? "\u2014";

  if (loading) {
    return (
      <KpiCardFrame title={title} href={href} className="animate-pulse motion-reduce:animate-none">
        <div role="status" aria-label={`Loading ${title}`} className="flex h-full flex-col gap-5">
          <div className="flex items-start justify-between gap-4">
            <div className="h-4 w-28 rounded bg-slate-700/80" />
            <div className="h-9 w-9 rounded-md bg-slate-700/70" />
          </div>
          <div className="h-9 w-20 rounded bg-slate-700/80" />
          <div className="mt-auto h-4 w-36 rounded bg-slate-700/60" />
        </div>
      </KpiCardFrame>
    );
  }

  if (error) {
    return (
      <KpiCardFrame title={title}>
        <article role="alert" className="flex min-h-28 flex-col justify-between gap-5">
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-sm font-medium text-slate-300">{title}</h2>
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-rose-300/20 bg-rose-300/10 text-sm font-semibold text-rose-100"
              aria-hidden="true"
            >
              !
            </div>
          </div>
          <p className="text-sm leading-6 text-rose-100">{error}</p>
        </article>
      </KpiCardFrame>
    );
  }

  if (empty) {
    return (
      <KpiCardFrame title={title} href={href}>
        <article
          className="flex min-h-28 flex-col justify-between gap-5"
          aria-label={`${title} empty`}
        >
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-sm font-medium text-slate-400">{title}</h2>
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-500/20 bg-slate-500/10 text-xs font-semibold text-slate-300"
              aria-hidden="true"
            >
              {icon}
            </div>
          </div>
          <p className="text-sm leading-6 text-slate-300">
            {description ?? "No data is available for this KPI yet."}
          </p>
          {href && actionLabel ? (
            <p className="text-sm font-semibold text-cyan-100">{actionLabel}</p>
          ) : null}
        </article>
      </KpiCardFrame>
    );
  }

  const headingId = kpiHeadingId(title);

  return (
    <KpiCardFrame title={title} href={href}>
      <article className="flex min-h-28 flex-col justify-between gap-5" aria-labelledby={headingId}>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2
              id={headingId}
              className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400"
            >
              {title}
            </h2>
            <p className="mt-3 text-[2rem] font-semibold leading-none text-slate-50">
              {displayValue}
            </p>
          </div>
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-cyan-300/20 bg-cyan-300/10 text-xs font-semibold text-cyan-100"
            aria-hidden="true"
          >
            {icon}
          </div>
        </div>
        <div className="space-y-2">
          {description ? <p className="text-sm text-slate-300">{description}</p> : null}
          <KpiTrend
            comparisonLabel={comparisonLabel}
            trendDirection={trendDirection}
            trendValue={trendValue}
          />
        </div>
      </article>
    </KpiCardFrame>
  );
}
