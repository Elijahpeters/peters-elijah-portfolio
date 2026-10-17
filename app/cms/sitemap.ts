import type { Content } from './content';
export function publicSitemap(c: Content, origin: string) {
  const routes = ['/', '/skyeta', '/skyeta/help', '/skyeta/privacy', '/skyeta/terms', '/projects/skyeta', '/projects/aurapass', '/projects/incubator-carrier', '/projects/circuits', ...[...c.projects, ...c.circuits].map(p => `/work/${p.slug}`)];
  return routes.map(path => ({
    url: new URL(path, origin).href,
    changeFrequency: 'monthly' as const,
    priority: path === '/' ? 1 : 0.8
  }));
}
