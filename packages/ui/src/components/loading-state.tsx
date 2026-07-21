import type { HTMLAttributes } from "react";

import { cn } from "../utils/cn";

export type LoadingStateProps = HTMLAttributes<HTMLDivElement> & {
  label?: string;
};

export function LoadingState({ className, label = "Loading", ...props }: LoadingStateProps) {
  return (
    <div
      aria-live="polite"
      className={cn("flex items-center gap-3 text-sm text-slate-600", className)}
      role="status"
      {...props}
    >
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-950"
      />
      <span>{label}</span>
    </div>
  );
}
