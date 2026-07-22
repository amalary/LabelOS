import { Card, PageHeader } from "@label-os/ui";

import { StatusIndicator } from "../../components/status-indicator";

type LoginPageProps = {
  searchParams?: Promise<{
    auth_error?: string | string[];
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const authError = params?.auth_error;
  const hasAuthError =
    authError === "sign_in_failed" ||
    (Array.isArray(authError) && authError.includes("sign_in_failed"));

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-10">
      <Card className="w-full max-w-sm">
        <PageHeader
          description="Sign in with WorkOS AuthKit."
          headingLevel={1}
          title="Login"
        />
        <a
          className="mt-6 inline-flex h-10 w-full items-center justify-center rounded-md border border-transparent bg-slate-950 px-4 text-sm font-medium text-white transition-colors hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-950"
          href="/api/auth/login"
        >
          Continue with WorkOS
        </a>
        {hasAuthError ? (
          <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            We could not complete sign-in. Please try again.
          </p>
        ) : null}
        <div className="mt-6 border-t border-slate-200 pt-6">
          <StatusIndicator />
        </div>
      </Card>
    </main>
  );
}
