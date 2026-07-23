import { LoginExperience } from "./login-experience";

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
    <main className="min-h-screen bg-[linear-gradient(135deg,#f8fafc_0%,#eef2f7_48%,#f8fafc_100%)] px-6 py-10">
      <LoginExperience hasAuthError={hasAuthError} />
    </main>
  );
}
