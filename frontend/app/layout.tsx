import type { Metadata, Viewport } from "next";
import { Noto_Sans, Dela_Gothic_One, Reggae_One } from "next/font/google";
import "./globals.css";

const notoSans = Noto_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-noto-sans",
});

const delaGothic = Dela_Gothic_One({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
  display: "swap",
});

const reggaeOne = Reggae_One({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-brush",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Offkai Bot",
  description: "Offkai RSVP & door check-in",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#E51F1F",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${notoSans.variable} ${delaGothic.variable} ${reggaeOne.variable}`}>
      <body className={`${notoSans.className} brand-bg paper-grain antialiased text-[#23110D]`}>
        {children}
      </body>
    </html>
  );
}
