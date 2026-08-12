import { Card, cn } from "@label-os/ui";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

type DashboardPanelProps = ComponentPropsWithoutRef<typeof Card> & {
  children: ReactNode;
};

export function DashboardPanel({ children, className, ...props }: DashboardPanelProps) {
  return (
    <Card className={cn("dashboard-panel rounded-[18px] p-5 shadow-none", className)} {...props}>
      {children}
    </Card>
  );
}
