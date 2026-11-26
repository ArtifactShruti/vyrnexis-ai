import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vyrnexis AI",
  description: "Autonomous enterprise intelligence"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
