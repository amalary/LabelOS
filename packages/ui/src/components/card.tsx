import type { HTMLAttributes } from "react";

import { cn } from "../utils/cn";

export type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className, ...props }: CardProps) {
  return (
    <div
      className={cn("rounded-md border border-slate-200 bg-white p-5 shadow-sm", className)}
      {...props}
    />
  );
}
