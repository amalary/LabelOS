import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const react = vi.hoisted(() => ({
  useActionState: vi.fn(),
}));

const reactDom = vi.hoisted(() => ({
  useFormStatus: vi.fn(),
}));

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useActionState: react.useActionState,
}));

vi.mock("react-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-dom")>()),
  useFormStatus: reactDom.useFormStatus,
}));

vi.mock("./actions", () => ({
  onboardWorkspace: vi.fn(),
}));

describe("WorkspaceOnboardingForm", () => {
  beforeEach(() => {
    vi.resetModules();
    react.useActionState.mockReturnValue([{ error: null }, vi.fn()]);
    reactDom.useFormStatus.mockReturnValue({ pending: false });
  });

  it("renders the initial organization name field", async () => {
    const { WorkspaceOnboardingForm } = await import("./onboarding-form");

    render(<WorkspaceOnboardingForm />);

    expect(screen.getByLabelText("Label or company name")).toBeRequired();
    expect(screen.getByRole("button", { name: "Create workspace" })).toBeEnabled();
  });

  it("renders loading and error states", async () => {
    react.useActionState.mockReturnValue([{ error: "WorkOS is unavailable." }, vi.fn()]);
    reactDom.useFormStatus.mockReturnValue({ pending: true });
    const { WorkspaceOnboardingForm } = await import("./onboarding-form");

    render(<WorkspaceOnboardingForm />);

    expect(screen.getByRole("alert")).toHaveTextContent("WorkOS is unavailable.");
    expect(screen.getByRole("button", { name: "Creating workspace..." })).toBeDisabled();
  });
});
