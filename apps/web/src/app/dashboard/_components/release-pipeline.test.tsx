import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReleasePipeline } from "./release-pipeline";
import type { ReleasePipelineData } from "./dashboard.types";

const lifecyclePipeline: ReleasePipelineData = {
  stages: [
    {
      status: "planning",
      label: "Planning",
      count: 0,
      href: "/releases?status=planning",
    },
    {
      status: "production",
      label: "Production",
      count: 1,
      href: "/releases?status=production",
    },
    {
      status: "distribution",
      label: "Distribution",
      count: 42,
      href: "/releases?status=distribution",
    },
    {
      status: "scheduled",
      label: "Scheduled",
      count: 1200,
      href: "/releases?status=scheduled",
    },
    {
      status: "released",
      label: "Released",
      count: 2500000,
      href: "/releases?status=released",
    },
  ],
};

describe("ReleasePipeline", () => {
  it("renders lifecycle stages with release counts and release status links", () => {
    render(<ReleasePipeline pipeline={lifecyclePipeline} />);

    expect(screen.getByRole("heading", { name: "Release Pipeline" })).toBeInTheDocument();
    expect(screen.getByLabelText("Release lifecycle stages")).toBeInTheDocument();
    expect(screen.getByText("2,501,243")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Planning: 0 releases" })).toHaveAttribute(
      "href",
      "/releases?status=planning",
    );
    expect(screen.getByRole("link", { name: "Production: 1 releases" })).toHaveAttribute(
      "href",
      "/releases?status=production",
    );
    expect(screen.getByRole("link", { name: "Released: 2,500,000 releases" })).toHaveAttribute(
      "href",
      "/releases?status=released",
    );
  });

  it("supports a zero-release pipeline", () => {
    render(
      <ReleasePipeline
        pipeline={{
          stages: lifecyclePipeline.stages.map((stage) => ({ ...stage, count: 0 })),
        }}
      />,
    );

    expect(screen.getAllByText("0")).toHaveLength(6);
    expect(screen.getByText("No releases are in the pipeline yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a release ->" })).toHaveAttribute(
      "href",
      "/releases/new",
    );
    expect(screen.getByText("Empty")).toBeInTheDocument();
  });

  it("renders loading, error, and empty organization states", () => {
    const { rerender } = render(<ReleasePipeline pipeline={{ stages: [], loading: true }} />);

    expect(screen.getByRole("status", { name: "Release pipeline loading" })).toBeInTheDocument();

    rerender(
      <ReleasePipeline pipeline={{ stages: [], error: "Release data could not be loaded." }} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Release data could not be loaded.");

    rerender(<ReleasePipeline pipeline={{ stages: [], emptyOrganization: true }} />);

    expect(
      screen.getByText("Select or create an organization to view release stages."),
    ).toBeInTheDocument();
  });
});
