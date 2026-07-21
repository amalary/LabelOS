import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "../utils/cn";

export type EmptyStateProps = HTMLAttributes<HTMLElement> & {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
};

export function EmptyState({
  action,
  className,
  description,
  icon,
  title,
  ...props
}: EmptyStateProps) {
  return (
    <section
      className={cn(
        "flex flex-col items-center justify-center rounded-md border border-dashed border-slate-300 bg-white px-6 py-10 text-center",
        className,
      )}
      {...props}
    >
      {icon ? (
        <div className="mb-4 text-slate-400" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      {description ? <p className="mt-2 max-w-md text-sm text-slate-600">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </section>
  );
}
