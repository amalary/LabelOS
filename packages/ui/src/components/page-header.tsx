import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "../utils/cn";

export type PageHeaderProps = HTMLAttributes<HTMLElement> & {
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
  headingLevel?: 1 | 2 | 3;
};

export function PageHeader({
  actions,
  className,
  description,
  eyebrow,
  headingLevel = 1,
  title,
  ...props
}: PageHeaderProps) {
  const Heading = `h${headingLevel}` as "h1" | "h2" | "h3";

  return (
    <header
      className={cn("flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between", className)}
      {...props}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-2 text-sm font-medium uppercase text-slate-500">{eyebrow}</p>
        ) : null}
        <Heading className="text-2xl font-semibold text-slate-950">{title}</Heading>
        {description ? (
          <p className="mt-2 max-w-2xl text-sm text-slate-600">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}
