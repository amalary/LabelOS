"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useActiveWorkspace } from "../lib/workspace-context";
import { YouTubeResearchPanel } from "./youtube-research-panel";
import { LocalResearchSetup } from "./local-research-setup";

type Candidate = {
  id: string;
  label: string;
  notes: string;
  status: string;
  revision: number;
  channel_id: string | null;
  source_expires_at: string | null;
};
type Policies = { privacyUrl?: string; termsUrl?: string; localSetup?: boolean };
const statuses = ["new", "reviewing", "shortlisted", "passed"];

export function ScoutingWorkspace(props: Policies) {
  const { activeWorkspace } = useActiveWorkspace();
  if (!activeWorkspace)
    return (
      <p>Choose a workspace using the workspace menu at the top of the page to scout artists.</p>
    );
  return <ScoutingPanel key={activeWorkspace.id} workspaceId={activeWorkspace.id} {...props} />;
}

export function ScoutingPanel({
  workspaceId,
  privacyUrl,
  termsUrl,
  localSetup,
}: Policies & { workspaceId: string }) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [runs, setRuns] = useState<{ id: string; label: string }[]>([]);
  const [runId, setRunId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [viewerVersion, setViewerVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(Date.now());
  const active = useRef(true);
  const listVersion = useRef(0);
  const base = `/api/workspaces/${encodeURIComponent(workspaceId)}/scouting`;
  const request = useCallback(
    async (path: string, method = "GET", body?: object) => {
      const response = await fetch(`${base}/${path}`, {
        method,
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok)
        throw new Error(
          response.status === 409
            ? "This candidate changed. Reopen it before saving your edits."
            : response.status === 401 || response.status === 403
              ? "You do not have scouting access in this workspace."
              : response.status === 404
                ? "This candidate is no longer available. Refresh the shortlist."
                : "Could not complete the request. Try again.",
        );
      return response.status === 204 ? null : response.json();
    },
    [base],
  );
  const refresh = useCallback(async () => {
    const version = ++listVersion.current;
    const data = await request(
      `candidates?limit=50&offset=${offset}${filter ? `&status=${filter}` : ""}`,
    );
    if (active.current && version === listVersion.current) {
      setCandidates(data);
      setLoaded(true);
    }
  }, [request, filter, offset]);
  useEffect(() => {
    active.current = true;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      active.current = false;
      listVersion.current++;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    const expired = (candidate: Candidate) =>
      candidate.channel_id &&
      (!candidate.source_expires_at || Date.parse(candidate.source_expires_at) <= now);
    if (selected && expired(selected)) {
      setSelected({ ...selected, channel_id: null, source_expires_at: null });
      setChannelId("");
      setViewerVersion((version) => version + 1);
    }
    if (candidates.some(expired))
      setCandidates(
        candidates.map((candidate) =>
          expired(candidate)
            ? { ...candidate, channel_id: null, source_expires_at: null }
            : candidate,
        ),
      );
  }, [now, selected, candidates]);
  useEffect(() => {
    setLoaded(false);
    void refresh().catch((err: Error) => {
      if (active.current) setError(err.message);
    });
  }, [refresh]);
  useEffect(() => {
    void request("runs")
      .then((data) => {
        if (active.current) {
          setRuns(data);
          setRunId(data[0]?.id ?? "");
        }
      })
      .catch((err: Error) => {
        if (active.current) setError(err.message);
      });
  }, [request]);

  async function action(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
    } catch (err) {
      if (active.current) setError((err as Error).message);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function save(channel: string) {
    await action(async () => {
      const data = await request("candidates", "POST", { channel_id: channel });
      if (active.current) {
        setSelected(data);
        setNotice("Candidate saved. Existing saves open the same candidate.");
      }
      await refresh();
    });
  }
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 text-slate-900">
      <header>
        <h1 className="text-3xl font-semibold">A&R scouting</h1>
        <p className="mt-2 text-slate-600">
          Discover channels and keep your team’s shortlist and human review in this workspace.
        </p>
      </header>
      {error && (
        <p role="alert" className="rounded border border-red-200 bg-red-50 p-3">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <section aria-label="Saved candidates" className="space-y-4 rounded border p-5">
        <h2 className="text-xl font-semibold">Shortlist</h2>
        <label>
          Review filter{" "}
          <select
            aria-label="Review filter"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All statuses</option>
            {statuses.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <button disabled={busy} onClick={() => void action(refresh)}>
          Refresh shortlist
        </button>
        {!loaded && !error && <p role="status">Loading shortlist…</p>}
        {loaded && candidates.length === 0 && <p>No saved candidates match this filter.</p>}
        <ul className="divide-y">
          {candidates.map((candidate) => (
            <li key={candidate.id} className="flex items-center justify-between py-3">
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    const data = await request(`candidates/${candidate.id}`);
                    if (active.current) setSelected(data);
                  })
                }
              >
                {candidate.label}
              </button>
              <span>{candidate.status}</span>
            </li>
          ))}
        </ul>
        <div className="flex gap-4">
          <button
            disabled={offset === 0 || busy}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Previous candidates
          </button>
          <button disabled={candidates.length < 50 || busy} onClick={() => setOffset(offset + 50)}>
            Next candidates
          </button>
        </div>
      </section>
      {selected && (
        <section aria-label="Candidate review" className="space-y-4 rounded border p-5">
          <h2 className="text-xl font-semibold">Candidate review</h2>
          <p>
            Labels and notes are your own observations. YouTube titles and counts are not copied
            here automatically.
          </p>
          <label className="block">
            Your label{" "}
            <input
              className="block w-full rounded border p-2"
              aria-label="Your label"
              maxLength={200}
              value={selected.label}
              onChange={(e) => setSelected({ ...selected, label: e.target.value })}
            />
          </label>
          <label className="block">
            Human notes{" "}
            <textarea
              className="block min-h-28 w-full rounded border p-2"
              aria-label="Human notes"
              maxLength={10000}
              value={selected.notes}
              onChange={(e) => setSelected({ ...selected, notes: e.target.value })}
            />
          </label>
          <label>
            Review status{" "}
            <select
              aria-label="Review status"
              value={selected.status}
              onChange={(e) => setSelected({ ...selected, status: e.target.value })}
            >
              {statuses.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-4">
            <button
              disabled={busy || !selected.label.trim()}
              onClick={() =>
                void action(async () => {
                  const data = await request(`candidates/${selected.id}`, "PATCH", {
                    label: selected.label,
                    notes: selected.notes,
                    status: selected.status,
                    revision: selected.revision,
                  });
                  if (active.current) {
                    setSelected(data);
                    setNotice("Review saved.");
                  }
                  await refresh();
                })
              }
            >
              Save review
            </button>
            {selected.channel_id && (
              <button
                disabled={busy || !runId}
                onClick={() => {
                  setChannelId(selected.channel_id!);
                  setViewerVersion((v) => v + 1);
                }}
              >
                Review current channel facts
              </button>
            )}
            {selected.channel_id && (
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await request(`candidates/${selected.id}/source`, "DELETE");
                    if (active.current) {
                      setSelected({ ...selected, channel_id: null, source_expires_at: null });
                      setChannelId("");
                      setViewerVersion((v) => v + 1);
                    }
                    await refresh();
                  })
                }
              >
                Remove saved YouTube reference
              </button>
            )}
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await request(`candidates/${selected.id}`, "DELETE");
                  if (active.current) {
                    setSelected(null);
                    setChannelId("");
                    setViewerVersion((v) => v + 1);
                  }
                  await refresh();
                })
              }
            >
              Delete candidate and notes
            </button>
          </div>
          {!selected.channel_id && (
            <p>
              The YouTube reference was removed or expired. Your human review remains available.
            </p>
          )}
        </section>
      )}
      {localSetup && (
        <LocalResearchSetup
          workspaceId={workspaceId}
          onPrepared={(run) => {
            if (!active.current) return;
            setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)]);
            setRunId(run.id);
            setNotice("Local research session is ready.");
          }}
        />
      )}
      {privacyUrl && termsUrl ? (
        <section>
          <label>
            Research session{" "}
            <select
              aria-label="Research session"
              value={runId}
              onChange={(e) => {
                setRunId(e.target.value);
                setChannelId("");
              }}
            >
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.label}
                </option>
              ))}
            </select>
          </label>
          {!runId ? (
            <p>
              A workspace governance manager must prepare a running YouTube research session before
              discovery is available.
            </p>
          ) : (
            <YouTubeResearchPanel
              key={`${runId}:${viewerVersion}`}
              workspaceId={workspaceId}
              runId={runId}
              privacyUrl={privacyUrl}
              termsUrl={termsUrl}
              initialChannel={channelId}
              onSave={save}
              onUnavailable={(channel) => {
                const clear = (candidate: Candidate) =>
                  candidate.channel_id === channel
                    ? { ...candidate, channel_id: null, source_expires_at: null }
                    : candidate;
                setCandidates((items) => items.map(clear));
                setSelected((candidate) => (candidate ? clear(candidate) : null));
                setChannelId("");
              }}
            />
          )}
        </section>
      ) : (
        <p>
          Channel discovery is awaiting configured privacy and terms documents. Saved human reviews
          remain available.
        </p>
      )}
    </div>
  );
}
