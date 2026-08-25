import { Card, cn } from "@label-os/ui";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

type DashboardPanelProps = ComponentPropsWithoutRef<typeof Card> & {
  children: ReactNode;
};

export function DashboardPanel({ children, className, ...props }: DashboardPanelProps) {
  return (
    <Card
      className={cn("dashboard-panel rounded-[16px] p-4 shadow-none sm:p-5", className)}
      {...props}
    >
      {children}
    </Card>
  );
}
