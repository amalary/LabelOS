import { Card, PageHeader } from "@label-os/ui";

import { StatusIndicator } from "../../components/status-indicator";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-10">
      <Card className="w-full max-w-sm">
        <PageHeader
          description="Sign in with the configured identity provider."
          headingLevel={1}
          title="Login"
        />
        <a
          className="mt-6 inline-flex h-10 w-full items-center justify-center rounded-md border border-transparent bg-slate-950 px-4 text-sm font-medium text-white transition-colors hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-950"
          href="/api/auth/login"
        >
          Continue with SSO
        </a>
        <div className="mt-6 border-t border-slate-200 pt-6">
          <StatusIndicator />
        </div>
      </Card>
    </main>
  );
}
