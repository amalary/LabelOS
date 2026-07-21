import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Label OS",
  description: "Frontend shell for Label OS.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
