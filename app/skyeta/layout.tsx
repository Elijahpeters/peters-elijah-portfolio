import type { Metadata } from "next";

const publicOrigin = "https://peterselijah.name.ng";
const skyetaTitle = "SkyETA — Compare flights and reliability evidence";
const skyetaDescription =
  "Compare current flights worldwide. Review historical reliability where records exist, with a separate trained model for selected U.S. domestic routes.";
const socialImage = "/skyeta/opengraph-image";

export const metadata: Metadata = {
  metadataBase: new URL(publicOrigin),
  alternates: {
    canonical: "/skyeta",
  },
  openGraph: {
    type: "website",
    url: "/skyeta",
    siteName: "SkyETA",
    title: skyetaTitle,
    description: skyetaDescription,
    images: [
      {
        url: socialImage,
        secureUrl: socialImage,
        type: "image/png",
        width: 1200,
        height: 630,
        alt: "SkyETA by Peters Elijah Temidayo",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: skyetaTitle,
    description: skyetaDescription,
    images: [socialImage],
  },
};

export default function SkyetaLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return children;
}
