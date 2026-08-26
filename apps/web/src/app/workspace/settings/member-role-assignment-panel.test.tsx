import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MemberRoleAssignmentsList,
  WorkspaceMembersList,
  WorkspaceRolesList,
} from "../../../lib/workspace-capabilities";

const mocks = vi.hoisted(() => ({
  authorization: {
    can: vi.fn(),
  },
  assignmentsReload: vi.fn(),
  replaceMemberWorkspaceRoles: vi.fn(),
  workspaceMembers: null as WorkspaceMembersList | null,
  workspaceRoles: null as WorkspaceRolesList | null,
  memberRoleAssignments: null as MemberRoleAssignmentsList | null,
}));

vi.mock("../../../lib/workspace-context", () => ({
  useActiveWorkspace: () => ({
    activeWorkspace: {
      id: "workspace_01",
      name: "Alpha Label",
    },
  }),
}));

vi.mock("../../../lib/workspace-capabilities", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/workspace-capabilities")>(
    "../../../lib/workspace-capabilities",
  );
  return {
    ...actual,
    replaceMemberWorkspaceRoles: mocks.replaceMemberWorkspaceRoles,
    useEffectiveCapabilities: () => mocks.authorization,
    useMemberRoleAssignments: () => ({
      data: mocks.memberRoleAssignments,
      error: null,
      isLoading: false,
      reload: mocks.assignmentsReload,
    }),
    useWorkspaceMembers: () => ({
      data: mocks.workspaceMembers,
      error: null,
      isLoading: false,
      reload: vi.fn(),
    }),
    useWorkspaceRoles: () => ({
      data: mocks.workspaceRoles,
      error: null,
      isLoading: false,
      reload: vi.fn(),
    }),
  };
});

const workspaceRoles: WorkspaceRolesList = {
  roles: [
    {
      id: "role_owner",
      key: "owner",
      name: "Owner",
      description: "Owner role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_ar",
      key: "a_and_r",
      name: "A&R",
      description: "A&R role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_manager",
      key: "manager",
      name: "Manager",
      description: "Manager role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_artist",
      key: "artist",
      name: "Artist",
      description: "Artist role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_producer",
      key: "producer",
      name: "Producer",
      description: "Producer role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_legal",
      key: "legal",
      name: "Legal",
      description: "Legal role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_marketing",
      key: "marketing",
      name: "Marketing",
      description: "Marketing role.",
      system_role: true,
      capabilities: [],
    },
    {
      id: "role_finance",
      key: "finance",
      name: "Finance",
      description: "Finance role.",
      system_role: true,
      capabilities: [],
    },
  ],
};

const workspaceMembers: WorkspaceMembersList = {
  members: [
    {
      id: "member_01",
      user_id: "user_01",
      email: "anthony@example.com",
      display_name: "Anthony Malary",
      workspace_permission: "member",
      role: "member",
      professional_roles: [],
      department_access: [],
      pending_department_access: [],
      denied_department_access: [],
      capability_permissions: [],
      status: "active",
    },
  ],
  limit: 100,
  offset: 0,
  total: 1,
};

const memberRoleAssignments: MemberRoleAssignmentsList = {
  assignments: [
    {
      member_id: "member_01",
      roles: [{ key: "artist", name: "Artist" }],
    },
  ],
};

describe("MemberRoleAssignmentPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authorization.can.mockReturnValue(true);
    mocks.assignmentsReload.mockResolvedValue(memberRoleAssignments);
    mocks.replaceMemberWorkspaceRoles.mockResolvedValue({ roles: [] });
    mocks.workspaceMembers = workspaceMembers;
    mocks.workspaceRoles = workspaceRoles;
    mocks.memberRoleAssignments = memberRoleAssignments;
  });

  it("allows authorized users to select multiple roles and save them", async () => {
    const user = userEvent.setup();
    const { MemberRoleAssignmentPanel } = await import("./member-role-assignment-panel");

    render(<MemberRoleAssignmentPanel />);

    expect(screen.getByText("Anthony Malary")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Owner/ })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Anthony Malary role Artist" })).toBeChecked();

    await user.click(screen.getByRole("checkbox", { name: "Anthony Malary role Producer" }));
    await user.click(screen.getByRole("checkbox", { name: "Anthony Malary role Manager" }));
    await user.click(screen.getByRole("button", { name: "Save roles" }));

    await waitFor(() =>
      expect(mocks.replaceMemberWorkspaceRoles).toHaveBeenCalledWith("workspace_01", "member_01", [
        "role_manager",
        "role_artist",
        "role_producer",
      ]),
    );
    expect(mocks.assignmentsReload).toHaveBeenCalled();
  });

  it("renders as view-only without the role assignment capability", async () => {
    mocks.authorization.can.mockReturnValue(false);
    const { MemberRoleAssignmentPanel } = await import("./member-role-assignment-panel");

    render(<MemberRoleAssignmentPanel />);

    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Anthony Malary role Artist" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save roles" })).toBeDisabled();
  });

  it("restores previous role selections when saving fails", async () => {
    const user = userEvent.setup();
    mocks.replaceMemberWorkspaceRoles.mockRejectedValue(new Error("failed"));
    const { MemberRoleAssignmentPanel } = await import("./member-role-assignment-panel");

    render(<MemberRoleAssignmentPanel />);

    const producer = screen.getByRole("checkbox", { name: "Anthony Malary role Producer" });
    await user.click(producer);
    expect(producer).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Save roles" }));

    await waitFor(() =>
      expect(
        screen.getByText("Role changes were not saved. The previous roles were restored."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("checkbox", { name: "Anthony Malary role Artist" })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Anthony Malary role Producer" }),
    ).not.toBeChecked();
  });
});
