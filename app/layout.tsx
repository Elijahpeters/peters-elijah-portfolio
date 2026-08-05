import type { Metadata } from "next";
import SectionAnalytics from "./components/SectionAnalytics";
import "./globals.css";

const title = "Peters Elijah Temidayo";
const description =
  "Portfolio of Peters Elijah Temidayo\u2014an Electrical & Electronics Engineer working across circuit design, AI/ML and hardware co-simulation.";
const socialImage = "/og-v2.jpg";
const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;
const umamiWebsiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
const umamiDomain = process.env.NEXT_PUBLIC_UMAMI_DOMAIN;
const analyticsEnabled =
  process.env.NODE_ENV === "production" &&
  Boolean(umamiWebsiteId && umamiDomain);

export const metadata: Metadata = {
  metadataBase: siteUrl ? new URL(siteUrl) : undefined,
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
    siteName: title,
    title,
    description,
    images: [
      {
        url: socialImage,
        secureUrl: socialImage,
        type: "image/jpeg",
        width: 1200,
        height: 630,
        alt: "Peters Elijah Temidayo, Electrical and Electronics Engineer",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
    images: [socialImage],
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
