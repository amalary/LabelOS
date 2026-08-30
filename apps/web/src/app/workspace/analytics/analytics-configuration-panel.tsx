"use client";

import { Button, Input, cn } from "@label-os/ui";
import { type FormEvent, useMemo, useState } from "react";

import {
  type AnalyticsMetricDefinition,
  type AnalyticsMetricValueType,
  type AnalyticsProvider,
  useAnalyticsMetricDefinitions,
  useAnalyticsProviders,
  useCreateAnalyticsMetricDefinition,
} from "../../../lib/analytics";
import { can, capabilities } from "../../../lib/authorization";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../../lib/workspace-context";

type FormState = {
  aggregation: string;
  defaultUnit: string;
  description: string;
  displayName: string;
  key: string;
  providerDisplayName: string;
  providerKey: string;
  providerType: string;
  valueType: AnalyticsMetricValueType;
};

const valueTypes: AnalyticsMetricValueType[] = ["integer", "decimal", "string", "boolean", "json"];
const canonicalNamePattern = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$/;

function initialFormState(providers: AnalyticsProvider[]): FormState {
  const provider = providers[0];
  return {
    aggregation: "sum",
    defaultUnit: "count",
    description: "",
    displayName: "",
    key: "",
    providerDisplayName: provider?.display_name ?? "Internal Analytics",
    providerKey: provider?.key ?? "internal",
    providerType: provider?.provider_type ?? "internal",
    valueType: "integer",
  };
}

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusLabel(): string {
  return "Not tracked";
}

function providerLabel(provider: AnalyticsProvider): string {
  return `${provider.display_name} (${provider.key})`;
}

function optionalValue(value: string): string | null {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function validateForm(form: FormState): string | null {
  if (!canonicalNamePattern.test(form.key.trim())) {
    return "Canonical name must use lowercase letters, numbers, underscores, and optional dot-separated segments.";
  }
  if (!form.displayName.trim()) {
    return "Display name is required.";
  }
  if (!form.providerKey.trim()) {
    return "Provider key is required.";
  }
  if (!form.providerType.trim()) {
    return "Provider type is required.";
  }
  return null;
}

function uniqueProviders(metrics: AnalyticsMetricDefinition[], providers: AnalyticsProvider[]) {
  const byId = new Map<string, AnalyticsProvider>();
  for (const provider of providers) {
    byId.set(provider.id, provider);
  }
  for (const metric of metrics) {
    byId.set(metric.provider.id, metric.provider);
  }
  return [...byId.values()].sort((left, right) => left.key.localeCompare(right.key));
}

export function AnalyticsConfigurationPanel() {
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const workspaceId = activeWorkspace?.id ?? null;
  const metrics = useAnalyticsMetricDefinitions(workspaceId);
  const providers = useAnalyticsProviders(workspaceId);
  const createMetric = useCreateAnalyticsMetricDefinition(workspaceId);
  const metricDefinitions = metrics.data?.metric_definitions ?? [];
  const providerList = useMemo(
    () => uniqueProviders(metricDefinitions, providers.data?.providers ?? []),
    [metricDefinitions, providers.data],
  );
  const [form, setForm] = useState<FormState>(() => initialFormState([]));
  const [formError, setFormError] = useState<string | null>(null);
  const [createdMessage, setCreatedMessage] = useState<string | null>(null);

  const canView = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.analyticsView)
    : false;
  const canCreate = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.analyticsCreate)
    : false;
  const isLoading =
    (metrics.isLoading && !metrics.data) ||
    (providers.isLoading && !providers.data) ||
    workspaceProfile.isLoading;
  const loadError = metrics.error || providers.error;

  function updateForm<Key extends keyof FormState>(key: Key, value: FormState[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
    setFormError(null);
    setCreatedMessage(null);
  }

  function useExistingProvider(providerId: string) {
    const provider = providerList.find((item) => item.id === providerId);
    if (!provider) {
      return;
    }
    setForm((current) => ({
      ...current,
      providerDisplayName: provider.display_name,
      providerKey: provider.key,
      providerType: provider.provider_type,
    }));
    setFormError(null);
    setCreatedMessage(null);
  }

  async function submitMetricDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validateForm(form);
    if (validationError) {
      setFormError(validationError);
      return;
    }
    try {
      const created = await createMetric.mutate({
        aggregation: optionalValue(form.aggregation),
        default_unit: optionalValue(form.defaultUnit),
        description: optionalValue(form.description),
        display_name: form.displayName.trim(),
        key: form.key.trim(),
        provider: {
          display_name: optionalValue(form.providerDisplayName),
          key: form.providerKey.trim(),
          provider_type: form.providerType.trim(),
        },
        value_type: form.valueType,
      });
      setCreatedMessage(`Metric definition ${created.display_name} is available.`);
      setForm(initialFormState(providerList));
      await Promise.all([metrics.reload(), providers.reload()]);
    } catch {
      setFormError("Metric definition could not be saved. Check the fields and try again.");
    }
  }

  if (!activeWorkspace) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <section className="border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Choose an active workspace before managing analytics configuration.
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <header className="flex flex-col gap-2 border-b border-slate-200 pb-5">
        <p className="text-sm font-medium text-slate-500">Workspace Analytics</p>
        <h1 className="text-3xl font-semibold tracking-normal text-slate-950">
          Analytics Configuration
        </h1>
        <p className="max-w-2xl text-sm leading-6 text-slate-600">
          Inspect workspace metric definitions and add custom definitions for internal reporting.
        </p>
      </header>

      {!canView && !workspaceProfile.isLoading ? (
        <section
          className="border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
          role="status"
        >
          Analytics configuration requires analytics view capability.
        </section>
      ) : null}

      {loadError ? (
        <section
          className="border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
          role="alert"
        >
          Analytics configuration could not be loaded.
        </section>
      ) : null}

      {isLoading ? (
        <section className="grid gap-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-20 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </section>
      ) : null}

      {canView && !isLoading ? (
        <>
          <section className="grid gap-4 border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Metric Definitions</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  Available canonical metrics for {activeWorkspace.name}.
                </p>
              </div>
              <span className="inline-flex h-8 items-center rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-semibold text-slate-600">
                {metricDefinitions.length} definitions
              </span>
            </div>

            {metricDefinitions.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
                No metric definitions are available for this workspace.
              </div>
            ) : (
              <div className="overflow-x-auto border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-3">Canonical Name</th>
                      <th className="px-3 py-3">Display Name</th>
                      <th className="px-3 py-3">Value Type</th>
                      <th className="px-3 py-3">Unit</th>
                      <th className="px-3 py-3">Provider</th>
                      <th className="px-3 py-3">State</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 bg-white">
                    {metricDefinitions.map((metric) => (
                      <tr key={metric.id}>
                        <td className="px-3 py-3 font-mono text-xs text-slate-900">{metric.key}</td>
                        <td className="px-3 py-3 font-medium text-slate-900">
                          {metric.display_name}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          {formatLabel(metric.value_type)}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          {metric.default_unit ?? "Not set"}
                        </td>
                        <td className="px-3 py-3 text-slate-600">
                          <span className="font-medium text-slate-800">
                            {metric.provider.display_name}
                          </span>
                          <span className="block font-mono text-xs text-slate-500">
                            {metric.provider.key} / {metric.provider.provider_type}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <span className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-semibold text-slate-600">
                            {statusLabel()}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="grid gap-4 border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Providers</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  Generic source records connected to workspace metric definitions.
                </p>
              </div>
              <span className="inline-flex h-8 items-center rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-semibold text-slate-600">
                {providerList.length} providers
              </span>
            </div>

            {providerList.length === 0 ? (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
                Providers appear after metric definitions are created.
              </div>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {providerList.map((provider) => (
                  <div
                    className="rounded-md border border-slate-200 bg-slate-50 p-3"
                    key={provider.id}
                  >
                    <div className="font-medium text-slate-950">{provider.display_name}</div>
                    <div className="mt-1 font-mono text-xs text-slate-500">{provider.key}</div>
                    <div className="mt-2 text-sm text-slate-600">
                      Source type: {provider.provider_type}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="grid gap-4 border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Custom Metric Definition</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  Add workspace-relevant definitions using typed analytics values.
                </p>
              </div>
              <span
                className={cn(
                  "inline-flex h-8 items-center rounded-md border px-3 text-xs font-semibold",
                  canCreate
                    ? "border-cyan-200 bg-cyan-50 text-cyan-700"
                    : "border-slate-200 bg-slate-50 text-slate-600",
                )}
              >
                {canCreate ? "Creation enabled" : "View only"}
              </span>
            </div>

            {!canCreate ? (
              <div
                className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
                role="status"
              >
                Creating metric definitions requires analytics create capability.
              </div>
            ) : null}

            {formError ? (
              <div
                className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
                role="alert"
              >
                {formError}
              </div>
            ) : null}

            {createdMessage ? (
              <div
                className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800"
                role="status"
              >
                {createdMessage}
              </div>
            ) : null}

            <form className="grid gap-4" onSubmit={(event) => void submitMetricDefinition(event)}>
              {providerList.length > 0 ? (
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Existing Provider
                  <select
                    className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => useExistingProvider(event.target.value)}
                    value=""
                  >
                    <option value="" disabled>
                      Select provider details
                    </option>
                    {providerList.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {providerLabel(provider)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Canonical Name
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("key", event.target.value)}
                    placeholder="campaign.streams"
                    value={form.key}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Display Name
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("displayName", event.target.value)}
                    placeholder="Campaign Streams"
                    value={form.displayName}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Value Type
                  <select
                    className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) =>
                      updateForm("valueType", event.target.value as AnalyticsMetricValueType)
                    }
                    value={form.valueType}
                  >
                    {valueTypes.map((valueType) => (
                      <option key={valueType} value={valueType}>
                        {formatLabel(valueType)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Unit
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("defaultUnit", event.target.value)}
                    placeholder="count, usd, percent"
                    value={form.defaultUnit}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Provider Key
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("providerKey", event.target.value)}
                    value={form.providerKey}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Provider Display Name
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("providerDisplayName", event.target.value)}
                    value={form.providerDisplayName}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Provider Type
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("providerType", event.target.value)}
                    value={form.providerType}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  Aggregation
                  <Input
                    disabled={!canCreate || createMetric.isMutating}
                    onChange={(event) => updateForm("aggregation", event.target.value)}
                    placeholder="sum, latest, count"
                    value={form.aggregation}
                  />
                </label>
              </div>

              <label className="grid gap-1 text-sm font-medium text-slate-700">
                Description
                <textarea
                  className="min-h-20 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                  disabled={!canCreate || createMetric.isMutating}
                  onChange={(event) => updateForm("description", event.target.value)}
                  value={form.description}
                />
              </label>

              <div className="flex justify-end">
                <Button disabled={!canCreate || createMetric.isMutating} type="submit">
                  {createMetric.isMutating ? "Creating..." : "Create metric definition"}
                </Button>
              </div>
            </form>
          </section>
        </>
      ) : null}
    </div>
  );
}
