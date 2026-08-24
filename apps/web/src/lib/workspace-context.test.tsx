import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ActiveWorkspaceProvider,
  toWorkspaceSelection,
  useActiveWorkspace,
} from "./workspace-context";
import type { OrganizationSelection } from "./organizations";

const selection: OrganizationSelection = {
  activeOrganization: {
    id: "local_org_01LABEL",
    name: "Northstar Audio",
    slug: "northstar-audio",
    role: "owner",
    can_switch: true,
  },
  organizations: [
    {
      id: "local_org_01LABEL",
      name: "Northstar Audio",
      slug: "northstar-audio",
      role: "owner",
      can_switch: true,
    },
    {
      id: "local_org_02LABEL",
      name: "Backup Label",
      slug: "backup-label",
      role: "member",
      can_switch: true,
    },
  ],
};

describe("workspace context", () => {
  it("maps WorkOS-backed organizations into LabelOS workspaces", () => {
    expect(toWorkspaceSelection(selection)).toEqual({
      activeWorkspace: selection.activeOrganization,
      workspaces: selection.organizations,
    });
  });

  it("exposes the active workspace to client components", () => {
    const { result } = renderHook(() => useActiveWorkspace(), {
      wrapper: ({ children }) => (
        <ActiveWorkspaceProvider selection={selection}>{children}</ActiveWorkspaceProvider>
      ),
    });

    expect(result.current.activeWorkspace?.name).toBe("Northstar Audio");
    expect(result.current.workspaces).toHaveLength(2);
    expect(result.current.hasActiveWorkspace).toBe(true);
  });
});
