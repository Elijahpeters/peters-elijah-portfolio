import type { Metadata } from 'next';
import type { Content } from './content';
export const siteOrigin = process.env.NEXT_PUBLIC_SITE_URL || 'https://peterselijah.name.ng';
export function contentMetadata(c: Content, path = '/', title = c.seo.title, description = c.seo.description, socialImage?: { url: string; alt: string }): Metadata {
  const image = socialImage || {
    url: c.seo.image,
    alt: `${c.profile.fullName} (${c.profile.alternateName}), ${c.profile.role}`
  };
  return {
    metadataBase: new URL(siteOrigin),
    title,
    description,
    alternates: {
      canonical: path
    },
    robots: {
      index: process.env.PORTFOLIO_PUBLIC === 'true',
      follow: true
    },
    openGraph: {
      type: 'website',
      title,
      description,
      url: path,
      siteName: c.profile.brand,
      images: [image]
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: [image]
    }
  };
}
export function personSchema(c: Content) {
  return {
    '@context': 'https://schema.org',
    '@type': 'Person',
    '@id': `${siteOrigin}/#person`,
    name: c.profile.fullName,
    alternateName: c.profile.alternateName,
    url: siteOrigin,
    image: new URL(c.profile.portrait, siteOrigin).href,
    jobTitle: c.profile.role,
    description: c.profile.introduction,
    alumniOf: {
      '@type': 'CollegeOrUniversity',
      name: 'Olabisi Onabanjo University'
    },
    knowsAbout: ['Electrical and Electronics Engineering', 'Circuit design', 'PCB development', 'Embedded systems', 'Power electronics', 'Hardware/software integration', 'Computer vision', 'Applied machine learning', 'AI model evaluation'],
    sameAs: [c.profile.linkedin, c.profile.github]
  };
}
