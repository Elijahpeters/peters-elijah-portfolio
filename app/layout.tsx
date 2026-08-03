import type { Metadata } from "next";
import "./globals.css";

const title = "Peters Elijah Temidayo";
const description =
  "Portfolio of Peters Elijah Temidayo\u2014an Electrical & Electronics Engineer working across circuit design, AI/ML and hardware co-simulation.";
const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;

export const metadata: Metadata = {
  metadataBase: siteUrl ? new URL(siteUrl) : undefined,
  title,
  description,
  icons: {
    icon: "/favicon.png",
    shortcut: "/favicon.png",
  },
  openGraph: {
    type: "website",
    title,
    description,
    images: [
      {
        url: "/og.png",
        width: 1731,
        height: 908,
        alt: "Peters Elijah Temidayo, Electrical and Electronics Engineer",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
    images: ["/og.png"],
  },
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
