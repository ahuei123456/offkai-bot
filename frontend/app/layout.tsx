import type { Metadata, Viewport } from "next";
import { Noto_Sans } from "next/font/google";
import "./globals.css";

const notoSans = Noto_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-noto-sans",
});

export const metadata: Metadata = {
  title: "chibachan",
  description: "offkai rsvp",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#30364F",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={notoSans.variable}>
      <body className={`${notoSans.className} antialiased bg-[#E1D9BC] text-[#30364F]`}>
        {children}
      </body>
    </html>
  );
}
