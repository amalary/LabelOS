"use client";

import {
  type ButtonHTMLAttributes,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import { cn } from "@label-os/ui";

import type { AuthActions, AuthUser } from "./auth-types";

const glassButton =
  "group inline-flex h-11 items-center justify-center gap-2 rounded-[22px] border border-white/65 bg-white/60 px-4 text-sm font-medium text-slate-900 shadow-[0_16px_40px_rgba(15,23,42,0.10)] backdrop-blur-2xl transition-all duration-200 ease-out hover:-translate-y-0.5 hover:bg-white/75 hover:shadow-[0_20px_50px_rgba(15,23,42,0.14)] active:translate-y-0 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500";

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900"
    />
  );
}

function WorkOsMark() {
  return (
    <span
      aria-hidden="true"
      className="flex h-5 w-5 items-center justify-center rounded-[8px] bg-slate-950 text-[10px] font-semibold text-white shadow-inner"
    >
      W
    </span>
  );
}

function SignOutIcon() {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24">
      <path
        d="M15.75 8.75 19 12m0 0-3.25 3.25M19 12H9.75M13 5.75h-1.6c-2.24 0-3.36 0-4.22.44a4 4 0 0 0-1.75 1.75C5 8.8 5 9.92 5 12.16v.68c0 2.24 0 3.36.43 4.22a4 4 0 0 0 1.75 1.75c.86.44 1.98.44 4.22.44H13"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function MenuIcon({ children }: { children: ReactNode }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-8 w-8 items-center justify-center rounded-2xl bg-white/65 text-slate-600 shadow-inner shadow-white/40"
    >
      {children}
    </span>
  );
}

function initialsFor(user?: AuthUser | null) {
  const source =
    [user?.firstName, user?.lastName].filter(Boolean).join(" ").trim() ||
    user?.name?.trim() ||
    user?.email?.split("@")[0] ||
    "User";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  const initials = parts
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");

  return initials || "U";
}

function displayUser(user?: AuthUser | null) {
  const safeName =
    [user?.firstName, user?.lastName].filter(Boolean).join(" ").trim() || user?.name?.trim();

  return {
    email: user?.email || "No email available",
    name: safeName || "User",
    organization: user?.organization?.trim() || "Personal Workspace",
    role: user?.role?.trim() || "Member",
    status: user?.status ?? "online",
  };
}

export type AvatarProps = {
  user?: AuthUser | null;
  size?: "sm" | "md" | "lg";
  className?: string;
};

export function Avatar({ className, size = "md", user }: AvatarProps) {
  const label = displayUser(user).name;
  const sizeClass = {
    lg: "h-14 w-14 text-base",
    md: "h-10 w-10 text-sm",
    sm: "h-8 w-8 text-xs",
  }[size];

  if (user?.imageUrl) {
    return (
      <span
        aria-label={`${label} profile`}
        className={cn(
          "inline-flex rounded-full bg-cover bg-center ring-1 ring-white/70",
          sizeClass,
          className,
        )}
        role="img"
        style={{ backgroundImage: `url("${user.imageUrl}")` }}
      />
    );
  }

  return (
    <span
      aria-label={`${label} profile`}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-slate-950 via-slate-700 to-sky-500 font-semibold text-white shadow-[0_10px_30px_rgba(15,23,42,0.20)] ring-1 ring-white/70",
        sizeClass,
        className,
      )}
      role="img"
    >
      {initialsFor(user)}
    </span>
  );
}

export type AuthButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  isLoading?: boolean;
};

export function SignInButton({ className, disabled, isLoading, ...props }: AuthButtonProps) {
  return (
    <button
      aria-busy={isLoading || undefined}
      className={cn(glassButton, "min-w-28", className)}
      disabled={disabled || isLoading}
      type="button"
      {...props}
    >
      {isLoading ? <Spinner /> : <WorkOsMark />}
      <span>{isLoading ? "Signing In" : "Sign In"}</span>
    </button>
  );
}

export function SignOutButton({ className, disabled, isLoading, ...props }: AuthButtonProps) {
  return (
    <button
      aria-busy={isLoading || undefined}
      className={cn(glassButton, "min-w-28 text-slate-700", className)}
      disabled={disabled || isLoading}
      type="button"
      {...props}
    >
      {isLoading ? <Spinner /> : <SignOutIcon />}
      <span>{isLoading ? "Signing Out" : "Sign Out"}</span>
    </button>
  );
}

export type SignedInUserSummaryProps = {
  user: AuthUser | null;
  className?: string;
};

export function SignedInUserSummary({ className, user }: SignedInUserSummaryProps) {
  const display = displayUser(user);

  return (
    <div
      className={cn(
        "grid min-w-0 grid-cols-[auto_1fr] items-center gap-3 rounded-[24px] border border-white/65 bg-white/55 px-3 py-2 shadow-[0_16px_42px_rgba(15,23,42,0.09)] backdrop-blur-2xl",
        className,
      )}
    >
      <div className="relative">
        <Avatar size="md" user={user} />
        <span
          aria-label={`${display.status} status`}
          className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white bg-emerald-400 shadow-[0_0_16px_rgba(52,211,153,0.8)]"
          role="img"
        />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-slate-950">{display.name}</p>
        <p className="truncate text-xs text-slate-500">
          {display.role} · {display.organization}
        </p>
      </div>
    </div>
  );
}

type MenuItem = {
  label: string;
  onSelect?: () => void;
  variant?: "default" | "danger";
  icon: ReactNode;
};

export type UserAccountMenuProps = AuthActions & {
  user: AuthUser | null;
  className?: string;
};

export function UserAccountMenu({
  className,
  onKeyboardShortcuts,
  onSettings,
  onSignOut,
  onTheme,
  user,
}: UserAccountMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const display = displayUser(user);
  const items = useMemo<MenuItem[]>(
    () => [
      {
        icon: (
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24">
            <path
              d="M5 12h14M12 5v14"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="1.8"
            />
          </svg>
        ),
        label: "Settings",
        onSelect: onSettings,
      },
      {
        icon: (
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24">
            <path
              d="M12 4.75v14.5M5.75 8.25h12.5M5.75 15.75h12.5"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="1.8"
            />
          </svg>
        ),
        label: "Theme",
        onSelect: onTheme,
      },
      {
        icon: (
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24">
            <path
              d="M7.5 8.5h9M7.5 12h9M7.5 15.5h5M5.75 4.75h12.5c.83 0 1.5.67 1.5 1.5v11.5c0 .83-.67 1.5-1.5 1.5H5.75c-.83 0-1.5-.67-1.5-1.5V6.25c0-.83.67-1.5 1.5-1.5Z"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="1.8"
            />
          </svg>
        ),
        label: "Keyboard Shortcuts",
        onSelect: onKeyboardShortcuts,
      },
      {
        icon: <SignOutIcon />,
        label: "Sign Out",
        onSelect: onSignOut,
        variant: "danger",
      },
    ],
    [onKeyboardShortcuts, onSettings, onSignOut, onTheme],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const firstItem = menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]');
    firstItem?.focus();

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !buttonRef.current?.contains(target)) {
        setIsOpen(false);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsOpen(false);
        buttonRef.current?.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

  function focusMenuItem(nextIndex: number) {
    const menuItems = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
    );
    const index = (nextIndex + menuItems.length) % menuItems.length;
    menuItems[index]?.focus();
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const menuItems = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
    );
    const currentIndex = menuItems.findIndex((item) => item === document.activeElement);

    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusMenuItem(currentIndex + 1);
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      focusMenuItem(currentIndex - 1);
    }

    if (event.key === "Tab" && menuItems.length > 0) {
      const first = menuItems[0];
      const last = menuItems[menuItems.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  }

  function onMenuItemClick(event: MouseEvent<HTMLButtonElement>, item: MenuItem) {
    event.preventDefault();
    item.onSelect?.();
    setIsOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <div className={cn("relative", className)}>
      <button
        ref={buttonRef}
        aria-controls={isOpen ? menuId : undefined}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label="Open account menu"
        className="rounded-full transition duration-200 hover:scale-[1.03] active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-500"
        onClick={() => setIsOpen((open) => !open)}
        type="button"
      >
        <Avatar size="md" user={user} />
      </button>
      <div
        className={cn(
          "absolute right-0 z-20 mt-3 w-80 origin-top-right rounded-[28px] border border-white/65 bg-white/72 p-3 opacity-0 shadow-[0_28px_80px_rgba(15,23,42,0.18)] ring-1 ring-slate-950/[0.03] backdrop-blur-3xl transition duration-200 ease-out",
          isOpen
            ? "pointer-events-auto translate-y-0 scale-100 opacity-100"
            : "pointer-events-none -translate-y-1 scale-[0.98]",
        )}
        hidden={!isOpen}
        id={menuId}
        onKeyDown={onMenuKeyDown}
        ref={menuRef}
        role="menu"
      >
        <div className="flex items-center gap-3 rounded-[22px] bg-white/55 p-3">
          <Avatar size="lg" user={user} />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-950">{display.name}</p>
            <p className="truncate text-xs text-slate-500">{display.email}</p>
          </div>
        </div>
        <div className="my-3 h-px bg-slate-950/10" role="separator" />
        <div className="flex flex-col gap-1">
          {items.map((item) => (
            <button
              className={cn(
                "flex h-11 items-center gap-3 rounded-[18px] px-2.5 text-left text-sm font-medium text-slate-700 transition duration-150 hover:bg-white/70 focus:bg-white/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500",
                item.variant === "danger" && "text-rose-700",
              )}
              key={item.label}
              onClick={(event) => onMenuItemClick(event, item)}
              role="menuitem"
              type="button"
            >
              <MenuIcon>{item.icon}</MenuIcon>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SkeletonLine({ className }: { className?: string }) {
  return <span className={cn("block rounded-full bg-slate-200/70 auth-shimmer", className)} />;
}

export function AuthenticationLoadingState({ className }: { className?: string }) {
  return (
    <div
      aria-label="Loading authentication"
      className={cn(
        "rounded-[28px] border border-white/65 bg-white/60 p-4 shadow-[0_18px_60px_rgba(15,23,42,0.10)] backdrop-blur-2xl",
        className,
      )}
      role="status"
    >
      <div className="flex items-center gap-3">
        <SkeletonLine className="h-11 w-11 rounded-full" />
        <div className="min-w-0 flex-1 space-y-2">
          <SkeletonLine className="h-3 w-32" />
          <SkeletonLine className="h-3 w-44" />
        </div>
      </div>
      <div className="mt-5 grid gap-2">
        <SkeletonLine className="h-10 w-full rounded-[18px]" />
        <SkeletonLine className="h-10 w-10/12 rounded-[18px]" />
        <SkeletonLine className="h-10 w-8/12 rounded-[18px]" />
      </div>
    </div>
  );
}

export type AuthenticationErrorStateProps = {
  headline?: string;
  supportingText?: string;
  onRetry?: () => void;
  onReturnHome?: () => void;
  className?: string;
};

export function AuthenticationErrorState({
  className,
  headline = "Authentication needs attention",
  onRetry,
  onReturnHome,
  supportingText = "We could not complete the secure sign-in flow. Try again or return home.",
}: AuthenticationErrorStateProps) {
  return (
    <section
      aria-labelledby="auth-error-heading"
      className={cn(
        "rounded-[28px] border border-white/65 bg-white/65 p-6 text-center shadow-[0_24px_70px_rgba(15,23,42,0.12)] backdrop-blur-2xl",
        className,
      )}
    >
      <div
        aria-hidden="true"
        className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-rose-50 text-rose-600 shadow-inner"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24">
          <path
            d="M12 8v4.25M12 16h.01M10.45 4.9 3.38 17.12A2 2 0 0 0 5.11 20h13.78a2 2 0 0 0 1.73-2.88L13.55 4.9a1.79 1.79 0 0 0-3.1 0Z"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.8"
          />
        </svg>
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-950" id="auth-error-heading">
        {headline}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-600">{supportingText}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <button className={glassButton} onClick={onRetry} type="button">
          Retry
        </button>
        <button
          className={cn(glassButton, "bg-white/35 text-slate-700")}
          onClick={onReturnHome}
          type="button"
        >
          Return Home
        </button>
      </div>
    </section>
  );
}

export type UnauthenticatedStateProps = {
  onSignIn: () => void;
  className?: string;
  showIllustration?: boolean;
};

export function UnauthenticatedState({
  className,
  onSignIn,
  showIllustration = true,
}: UnauthenticatedStateProps) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-[28px] border border-white/65 bg-white/62 p-8 shadow-[0_28px_90px_rgba(15,23,42,0.12)] backdrop-blur-3xl",
        className,
      )}
    >
      <div className="flex flex-col gap-8 md:flex-row md:items-center md:justify-between">
        <div className="max-w-lg">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-[20px] bg-slate-950 text-sm font-semibold text-white shadow-[0_18px_40px_rgba(15,23,42,0.22)]">
              LO
            </span>
            <span className="text-sm font-semibold text-slate-700">Label OS</span>
          </div>
          <h1 className="mt-7 text-3xl font-semibold tracking-normal text-slate-950">
            Welcome to your labeling workspace
          </h1>
          <p className="mt-4 text-base leading-7 text-slate-600">
            Coordinate production data, review workflows, and AI-assisted labeling from one calm
            operating surface.
          </p>
          <div className="mt-7">
            <SignInButton onClick={onSignIn} />
          </div>
        </div>
        {showIllustration ? (
          <div
            aria-hidden="true"
            className="min-h-52 flex-1 rounded-[28px] border border-white/60 bg-[radial-gradient(circle_at_30%_25%,rgba(125,211,252,0.45),transparent_34%),linear-gradient(135deg,rgba(255,255,255,0.86),rgba(226,232,240,0.58))] p-5 shadow-inner"
          >
            <div className="grid h-full min-h-44 grid-cols-3 gap-3">
              <div className="rounded-[22px] bg-white/70 shadow-sm" />
              <div className="rounded-[22px] bg-slate-950/80 shadow-sm" />
              <div className="rounded-[22px] bg-white/70 shadow-sm" />
              <div className="col-span-2 rounded-[22px] bg-white/65 shadow-sm" />
              <div className="rounded-[22px] bg-sky-200/70 shadow-sm" />
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
