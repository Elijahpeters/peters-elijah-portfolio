import type { Metadata } from "next";
import SectionAnalytics from "./components/SectionAnalytics";
import "./globals.css";

const title = "Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer";
const description =
  "Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.";
const socialImage = "/og-v2.jpg";
const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://peterselijah.name.ng";
const umamiWebsiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
const umamiDomain = process.env.NEXT_PUBLIC_UMAMI_DOMAIN;
const analyticsEnabled =
  process.env.NODE_ENV === "production" &&
  Boolean(umamiWebsiteId && umamiDomain);

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  robots: { index: process.env.PORTFOLIO_PUBLIC === "true", follow: true },
  title,
  description,
  alternates: {
    canonical: "/",
  },
  icons: {
    icon: "/favicon.png",
    shortcut: "/favicon.png",
  },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "Elijah Peters | Engineering Portfolio",
    title,
    description,
    images: [
      {
        url: socialImage,
        secureUrl: socialImage,
        type: "image/jpeg",
        width: 1200,
        height: 630,
        alt: "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
    images: [{ url: socialImage, alt: "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        {analyticsEnabled ? (
          <script
            defer
            src="https://cloud.umami.is/script.js"
            data-website-id={umamiWebsiteId}
            data-domains={umamiDomain}
            data-do-not-track="true"
            data-exclude-search="true"
            data-exclude-hash="true"
          />
        ) : null}
      </head>
      <body>
        {children}
        {analyticsEnabled ? <SectionAnalytics /> : null}
      </body>
    </html>
  );
}
