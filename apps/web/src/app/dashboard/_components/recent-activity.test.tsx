import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RecentActivity } from "./recent-activity";

const now = new Date("2026-08-12T18:00:00.000Z");

describe("RecentActivity", () => {
  it("renders mapped activity events", () => {
    render(
      <RecentActivity
        now={now}
        activity={{
          events: [
            {
              id: "activity-01",
              type: "artist.created",
              payload: { name: "NOVA" },
              createdAt: "2026-08-12T17:56:00.000Z",
            },
            {
              id: "activity-02",
              type: "member.joined",
              payload: { displayName: "Sarah" },
              createdAt: "2026-08-12T17:28:00.000Z",
            },
          ],
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Recent Activity" })).toBeInTheDocument();
    expect(screen.getByText("Artist created")).toBeInTheDocument();
    expect(screen.getByText("NOVA was added")).toBeInTheDocument();
    expect(screen.getByText("4 minutes ago")).toBeInTheDocument();
    expect(screen.getByText("Member joined")).toBeInTheDocument();
    expect(screen.getByText("Sarah joined the organization")).toBeInTheDocument();
    expect(screen.getByText("32 minutes ago")).toBeInTheDocument();
  });

  it("renders empty, loading, and error states", () => {
    const { rerender } = render(<RecentActivity activity={{ events: [] }} />);

    expect(screen.getByText("No recent activity yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add your first artist ->" })).toHaveAttribute(
      "href",
      "/dashboard/artists/new",
    );

    rerender(<RecentActivity activity={{ events: [], loading: true }} />);
    expect(screen.getByLabelText("Recent activity loading")).toBeInTheDocument();

    rerender(<RecentActivity activity={{ events: [], error: "Realtime events timed out." }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Realtime events timed out.");
  });

  it("renders unknown activity event types with their raw type", () => {
    render(
      <RecentActivity
        now={now}
        activity={{
          events: [
            {
              id: "activity-unknown",
              type: "release.approval_escalated",
              actor: { displayName: "Mara" },
              entityType: "approval",
              createdAt: "2026-08-12T17:00:00.000Z",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Release Approval Escalated")).toBeInTheDocument();
    expect(screen.getByText("release.approval_escalated")).toBeInTheDocument();
    expect(screen.getByText("Mara made an update to approval")).toBeInTheDocument();
  });
});
