import type { Metadata } from "next";
import { Open_Sans } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { MarketTimeBar } from "@/components/layout/MarketTimeBar";
import { Toaster } from "sonner";

const openSans = Open_Sans({
  variable: "--font-open-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Trade Brain",
  description: "Advisory-only Indian equity research for NSE/BSE",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${openSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex">
        <Sidebar />
        <main className="flex-1 ml-64 min-h-screen bg-background">
          <MarketTimeBar />
          {children}
        </main>
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
