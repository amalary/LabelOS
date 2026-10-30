"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import {
  type ChannelCandidate,
  type ChannelDisplay,
  counterText,
  isDisplayable,
  researchMessages,
} from "../lib/youtube-research";

export function YouTubeResearchPanel({
  workspaceId,
  runId,
  privacyUrl,
  termsUrl,
  onSave,
  initialChannel = "",
  onUnavailable,
}: {
  workspaceId: string;
  runId: string;
  privacyUrl: string;
  termsUrl: string;
  onSave?: (channelId: string) => Promise<void>;
  initialChannel?: string;
  onUnavailable?: (channelId: string) => void;
}) {
  const [accepted, setAccepted] = useState(false);
  const [query, setQuery] = useState("");
  const [channelId, setChannelId] = useState(initialChannel);
  const [saving, setSaving] = useState(false);
  const [results, setResults] = useState<ChannelCandidate[]>([]);
  const [selected, setSelected] = useState<ChannelDisplay | null>(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [retryAt, setRetryAt] = useState(0);
  const [expired, setExpired] = useState(false);
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  const base = `/api/workspaces/${encodeURIComponent(workspaceId)}/research/youtube/runs/${encodeURIComponent(runId)}`;

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(timer);
      generation.current++;
      active.current?.abort();
    };
  }, []);

  useEffect(() => {
    const remaining = results.filter((item) => isDisplayable(item.provenance, now));
    if (remaining.length !== results.length) {
      setResults(remaining);
      setExpired(true);
    }
    if (
      selected &&
      (!isDisplayable(selected.artist.provenance, now) ||
        selected.items.some((entry) => !isDisplayable(entry.provenance, now)))
    ) {
      setSelected(null);
      setChannelId("");
      setExpired(true);
    }
  }, [now, results, selected]);

  async function request(operation: "search" | "channel", body: object) {
    if (active.current || Date.now() < retryAt || !accepted) return;
    const token = ++generation.current;
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    setError(null);
    setExpired(false);
    const timeout = setTimeout(() => controller.abort(), 20_000);
    try {
      const response = await fetch(`${base}/${operation}`, {
        method: "POST",
        cache: "no-store",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (token !== generation.current) return;
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        if (token !== generation.current) return;
        const code =
          response.status === 409 || response.status === 403 || response.status === 401
            ? "ineligible"
            : String(failure.detail?.code ?? "error");
        setError(code in researchMessages ? code : "error");
        const retry = Number(response.headers.get("Retry-After"));
        setRetryAt(Date.now() + (Number.isFinite(retry) && retry > 0 ? retry : 2) * 1000);
        if (code === "data_unavailable" || code === "ineligible") {
          setSelected(null);
          setResults([]);
          setChannelId("");
          if (
            code === "data_unavailable" &&
            "channel_id" in body &&
            typeof body.channel_id === "string"
          ) {
            onUnavailable?.(body.channel_id);
          }
        }
        return;
      }
      const data = await response.json();
      if (token !== generation.current) return;
      if (operation === "search") {
        setResults(data.items);
        setSearched(true);
      } else {
        setSelected(data);
        setResults((items) =>
          items.map((item) => (item.external_id === data.artist.external_id ? data.artist : item)),
        );
      }
    } catch {
      if (token === generation.current) setError(controller.signal.aborted ? "timeout" : "error");
    } finally {
      clearTimeout(timeout);
      if (token === generation.current) {
        active.current = null;
        setLoading(false);
      }
    }
  }

  async function forget() {
    generation.current++;
    active.current?.abort();
    active.current = null;
    setLoading(false);
    setSelected(null);
    setResults([]);
    setQuery("");
    setChannelId("");
    setSearched(false);
    setExpired(true);
    setError(null);
    try {
      await fetch(`${base}/display-cache`, { method: "DELETE", cache: "no-store" });
    } catch {
      /* Server copies expire automatically within 60 seconds. */
    }
  }

  const visible =
    selected &&
    isDisplayable(selected.artist.provenance, now) &&
    selected.items.every((item) => isDisplayable(item.provenance, now))
      ? selected
      : null;
  const disabled = loading || now < retryAt || !accepted;
  return (
    <section className="mx-auto max-w-4xl space-y-6 p-6" aria-label="YouTube research">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold">Channel research</h1>
        <a
          href="https://www.youtube.com/"
          aria-label="YouTube"
          className="inline-block rounded bg-white p-4"
        >
          <Image
            src="/brands/youtube.svg"
            alt="YouTube"
            width={246}
            height={55}
            className="h-auto w-[123px]"
            unoptimized
          />
        </a>
        <p>Public channel information from YouTube. A channel is not a verified artist identity.</p>
        <p>
          Views, videos and subscriber counts are display only. Unavailable counts are not zero.
        </p>
        <p>
          <a href={privacyUrl}>Privacy policy</a> · <a href={termsUrl}>LabelOS terms</a> ·{" "}
          <a href="https://www.youtube.com/t/terms">YouTube Terms of Service</a> ·{" "}
          <a href="https://policies.google.com/privacy">Google Privacy Policy</a>
        </p>
        <label>
          <input
            type="checkbox"
            checked={accepted}
            onChange={(event) => {
              setAccepted(event.target.checked);
              if (!event.target.checked) void forget();
            }}
          />{" "}
          I agree to the privacy policy, LabelOS terms and YouTube Terms of Service.
        </label>
      </header>
      <form
        className="flex gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) void request("search", { query: query.trim(), limit: 10 });
        }}
      >
        <input
          aria-label="Search YouTube channels"
          maxLength={500}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="rounded border p-2"
        />
        <button disabled={disabled || !query.trim()} type="submit">
          Search channels
        </button>
      </form>
      <form
        className="flex gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setSelected(null);
          void request("channel", { channel_id: channelId.trim() });
        }}
      >
        <input
          aria-label="YouTube channel ID"
          value={channelId}
          maxLength={24}
          onChange={(event) => setChannelId(event.target.value)}
          className="rounded border p-2"
        />
        <button disabled={disabled || !/^UC[A-Za-z0-9_-]{22}$/.test(channelId.trim())}>
          Look up channel
        </button>
      </form>
      {loading && <p role="status">Loading YouTube data…</p>}
      {error && <p role="alert">{researchMessages[error]}</p>}
      {now < retryAt && (
        <p role="status">Requests can resume in {Math.ceil((retryAt - now) / 1000)} seconds.</p>
      )}
      {expired && (
        <p role="status">
          YouTube display data removed. Search again to load current data. This does not delete data
          on YouTube.
        </p>
      )}
      {searched && !loading && results.length === 0 && !error && (
        <p>No current results. Try another search or refresh expired results.</p>
      )}
      <ul className="space-y-3">
        {results
          .filter((item) => isDisplayable(item.provenance, now))
          .map((item) => (
            <li key={item.external_id}>
              <button
                disabled={disabled}
                onClick={() => {
                  setSelected(null);
                  void request("channel", { channel_id: item.external_id });
                }}
              >
                {item.name}
              </button>
              {now - Date.parse(item.provenance.collected_at) >= 60_000 && (
                <span> — Stale; refresh before relying on this data.</span>
              )}
            </li>
          ))}
      </ul>
      {visible && (
        <article className="space-y-3 rounded border p-4">
          <h2 className="text-xl">{visible.artist.name}</h2>
          <a
            href={`https://www.youtube.com/channel/${encodeURIComponent(visible.artist.external_id)}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            View channel on YouTube
          </a>
          <p>Updated {new Date(visible.artist.provenance.collected_at).toLocaleString()}</p>
          {(error || now - Date.parse(visible.artist.provenance.collected_at) >= 60_000) && (
            <p role="status">Stale YouTube data — refresh before relying on these counts.</p>
          )}
          <dl>
            {["views", "subscribers", "videos"].map((metric) => (
              <div key={metric}>
                <dt>{metric}</dt>
                <dd>{counterText(visible, metric)}</dd>
              </div>
            ))}
          </dl>
          <button
            disabled={disabled}
            onClick={() => void request("channel", { channel_id: visible.artist.external_id })}
          >
            Refresh channel
          </button>
          {onSave && (
            <button
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSave(visible.artist.external_id);
                } catch {
                  setError("error");
                } finally {
                  setSaving(false);
                }
              }}
            >
              {saving ? "Saving candidate…" : "Save candidate"}
            </button>
          )}
        </article>
      )}
      <button onClick={() => void forget()}>Clear YouTube display data</button>
      <p>
        Data is kept briefly in memory and removed when this view closes or expires. No automatic
        searches or background refreshes run.
      </p>
    </section>
  );
}
