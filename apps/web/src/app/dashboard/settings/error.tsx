"use client";

import { Button } from "@label-os/ui";

export default function OrganizationSettingsError({ reset }: { reset: () => void }) {
  return (
    <div
      className="rounded-md border border-red-200 bg-red-50 px-5 py-4 text-sm leading-6 text-red-950"
      role="alert"
    >
      <h2 className="font-semibold">Organization settings could not be loaded.</h2>
      <p className="mt-1">Refresh the page or try again after your session is updated.</p>
      <Button className="mt-4" onClick={reset} size="sm" type="button" variant="secondary">
        Try again
      </Button>
    </div>
  );
}
