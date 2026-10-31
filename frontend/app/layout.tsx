import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Call Assistant",
  description: "A personal AI receptionist for calls you cannot answer.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
