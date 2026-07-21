import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("defaults to a non-submit button and renders caller content", () => {
    render(<Button>Save label</Button>);

    expect(screen.getByRole("button", { name: "Save label" })).toHaveAttribute("type", "button");
  });

  it("supports deterministic click interactions", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(<Button onClick={onClick}>Create task</Button>);

    await user.click(screen.getByRole("button", { name: "Create task" }));

    expect(onClick).toHaveBeenCalledOnce();
  });
});
