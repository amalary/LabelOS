import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  WorkspaceCapabilityApiError,
  clearWorkspaceCapabilityCache,
  getCurrentWorkspaceAuthorization,
  getCurrentWorkspaceRoles,
  getEffectiveCapabilities,
  getMemberRoleAssignments,
  getWorkspaceMembers,
  getWorkspaceRoles,
  invalidateWorkspaceCapabilityCache,
  replaceMemberWorkspaceRoles,
  shouldInvalidateWorkspaceCapabilityRealtimeCacheKey,
  useCapabilities,
  useCurrentWorkspaceRoles,
  useEffectiveCapabilities,
  useMemberRoleAssignments,
  useWorkspaceMembers,
  useWorkspaceRoles,
} from "./workspace-capabilities";

const authorizationContext = {
  workspace_id: "workspace_01",
  roles: [
    {
      key: "manager",
      name: "Manager",
    },
  ],
  capabilities: ["artist.profile.view", "artist.profile.edit"],
};

const ownerAuthorizationContext = {
  workspace_id: "workspace_01",
  roles: [
    {
      key: "artist",
      name: "Artist",
    },
    {
      key: "owner",
      name: "Owner",
    },
  ],
  capabilities: ["workspace.view"],
};

const workspaceRoles = {
  roles: [
    {
      id: "role_01",
      key: "artist",
      name: "Artist",
      description: "Artist role",
      system_role: true,
      capabilities: ["artist.profile.view"],
    },
  ],
};

const workspaceMembers = {
  members: [
    {
      id: "member_01",
      user_id: "user_01",
      email: "anthony@example.com",
      display_name: "Anthony Malary",
      workspace_permission: "member",
      role: "member",
      professional_roles: ["Artist"],
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

const memberRoleAssignments = {
  assignments: [
    {
      member_id: "member_01",
      roles: [
        {
          key: "artist",
          name: "Artist",
        },
      ],
    },
  ],
};

describe("workspace capability data layer", () => {
  beforeEach(() => {
    clearWorkspaceCapabilityCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetches current workspace authorization through the frontend proxy", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(authorizationContext))
      .mockResolvedValueOnce(Response.json(authorizationContext))
      .mockResolvedValueOnce(Response.json(authorizationContext));

    await expect(getCurrentWorkspaceAuthorization("workspace_01")).resolves.toEqual(
      authorizationContext,
    );
    await expect(getEffectiveCapabilities("workspace_01")).resolves.toEqual([
      "artist.profile.view",
      "artist.profile.edit",
    ]);
    await expect(getCurrentWorkspaceRoles("workspace_01")).resolves.toEqual([
      {
        key: "manager",
        name: "Manager",
      },
    ]);

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/authorization/context",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("fetches available workspace roles and member role assignments", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(workspaceRoles))
      .mockResolvedValueOnce(Response.json(workspaceMembers))
      .mockResolvedValueOnce(Response.json(memberRoleAssignments));

    await expect(getWorkspaceRoles("workspace_01")).resolves.toEqual(workspaceRoles);
    await expect(getWorkspaceMembers("workspace_01")).resolves.toEqual(workspaceMembers);
    await expect(getMemberRoleAssignments("workspace_01")).resolves.toEqual(memberRoleAssignments);

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/roles",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/members?limit=100&offset=0",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "/api/workspaces/workspace_01/member-role-assignments",
      expect.any(Object),
    );
  });

  it("replaces member workspace roles through the frontend proxy", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ roles: [] }))
      .mockResolvedValueOnce(Response.json(memberRoleAssignments));

    await expect(
      replaceMemberWorkspaceRoles("workspace_01", "member_01", ["role_artist", "role_manager"]),
    ).resolves.toEqual({ roles: [] });
    await expect(getMemberRoleAssignments("workspace_01")).resolves.toEqual(memberRoleAssignments);

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/members/member_01/roles",
      expect.objectContaining({
        body: JSON.stringify({ role_ids: ["role_artist", "role_manager"] }),
        cache: "no-store",
        method: "PUT",
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("maps authorization failures to typed loading errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "Forbidden" }, { status: 403 }));

    await expect(getWorkspaceRoles("workspace_01")).rejects.toBeInstanceOf(
      WorkspaceCapabilityApiError,
    );
    await expect(getWorkspaceRoles("workspace_01")).rejects.toMatchObject({
      code: "forbidden",
      status: 403,
    });
  });

  it("loads effective capability state and exposes can and hasCapability checks", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(authorizationContext));

    const { result } = renderHook(() => useCapabilities("workspace_01"));

    expect(result.current.isLoading).toBe(true);
    await waitFor(() =>
      expect(result.current.capabilities).toEqual(["artist.profile.view", "artist.profile.edit"]),
    );
    expect(result.current.can("artist.profile.edit")).toBe(true);
    expect(result.current.hasCapability("artist.profile.delete")).toBe(false);
    expect(result.current.roles).toEqual([{ key: "manager", name: "Manager" }]);
  });

  it("treats owner as capable even when role ordering is not legacy-role first", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(ownerAuthorizationContext));

    const { result } = renderHook(() => useEffectiveCapabilities("workspace_01"));

    await waitFor(() => expect(result.current.subject?.workspacePermission).toBe("owner"));
    expect(result.current.can("artist.profile.delete")).toBe(true);
  });

  it("uses workspace-scoped cache keys so switching workspaces loads fresh capability state", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(authorizationContext))
      .mockResolvedValueOnce(
        Response.json({
          workspace_id: "workspace_02",
          roles: [{ key: "legal", name: "Legal" }],
          capabilities: ["contract.view"],
        }),
      );

    let workspaceId = "workspace_01";
    const { result, rerender } = renderHook(() => useEffectiveCapabilities(workspaceId));

    await waitFor(() => expect(result.current.can("artist.profile.edit")).toBe(true));

    workspaceId = "workspace_02";
    rerender();

    await waitFor(() => expect(result.current.capabilities).toEqual(["contract.view"]));
    expect(result.current.can("artist.profile.edit")).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("loads available roles and authorized member role assignments with hook loading state", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(workspaceRoles))
      .mockResolvedValueOnce(Response.json(workspaceMembers))
      .mockResolvedValueOnce(Response.json(memberRoleAssignments));

    const roles = renderHook(() => useWorkspaceRoles("workspace_01"));
    const members = renderHook(() => useWorkspaceMembers("workspace_01"));
    const assignments = renderHook(() => useMemberRoleAssignments("workspace_01"));

    await waitFor(() => expect(roles.result.current.data).toEqual(workspaceRoles));
    await waitFor(() => expect(members.result.current.data).toEqual(workspaceMembers));
    await waitFor(() => expect(assignments.result.current.data).toEqual(memberRoleAssignments));
    expect(roles.result.current.isLoading).toBe(false);
    expect(assignments.result.current.error).toBeNull();
  });

  it("derives current user workspace roles from the authorization context cache", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(authorizationContext));

    const roles = renderHook(() => useCurrentWorkspaceRoles("workspace_01"));
    const capabilities = renderHook(() => useEffectiveCapabilities("workspace_01"));

    await waitFor(() => expect(roles.result.current.data).toEqual(authorizationContext.roles));
    expect(capabilities.result.current.capabilities).toEqual(authorizationContext.capabilities);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("invalidates loaded capability state after role or membership changes", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(authorizationContext))
      .mockResolvedValueOnce(
        Response.json({
          ...authorizationContext,
          capabilities: ["artist.profile.view"],
        }),
      );

    const { result } = renderHook(() => useEffectiveCapabilities("workspace_01"));

    await waitFor(() => expect(result.current.can("artist.profile.edit")).toBe(true));

    invalidateWorkspaceCapabilityCache((key) =>
      shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
        key,
        organizationId: "workspace_01",
      }),
    );

    await waitFor(() => expect(result.current.can("artist.profile.edit")).toBe(false));
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("targets workspace capability cache keys for realtime membership updates", () => {
    expect(
      shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
        key: "workspace-capabilities:authorization-context:workspace_01",
        organizationId: "workspace_01",
      }),
    ).toBe(true);
    expect(
      shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
        key: "workspace-capabilities:member-role-assignments:workspace_01",
        organizationId: "workspace_01",
      }),
    ).toBe(true);
    expect(
      shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
        key: "workspace-capabilities:members:workspace_01:100:0",
        organizationId: "workspace_01",
      }),
    ).toBe(true);
    expect(
      shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
        key: "workspace-capabilities:authorization-context:workspace_02",
        organizationId: "workspace_01",
      }),
    ).toBe(false);
  });
});
