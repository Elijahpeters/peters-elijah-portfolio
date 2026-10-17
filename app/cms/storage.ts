import { initialContent, validateContent, type Content } from './content.ts';
export type Snapshot = {
  draft: Content;
  published: Content;
  revision: number;
  publishedAt: string | null;
};
export async function load(db?: D1Database): Promise<Snapshot> {
  if (!db) return {
    draft: initialContent,
    published: initialContent,
    revision: 0,
    publishedAt: null
  };
  const row = await db.prepare('SELECT draft, published, revision, published_at FROM portfolio_content WHERE id = 1').first<{
    draft: string;
    published: string;
    revision: number;
    published_at: string | null;
  }>();
  if (!row) return {
    draft: initialContent,
    published: initialContent,
    revision: 0,
    publishedAt: null
  };
  return {
    draft: validateContent(JSON.parse(row.draft)),
    published: validateContent(JSON.parse(row.published)),
    revision: row.revision,
    publishedAt: row.published_at
  };
}
export async function saveDraft(db: D1Database, content: Content, revision: number) {
  const json = JSON.stringify(validateContent(content));
  await db.prepare('INSERT OR IGNORE INTO portfolio_content (id, draft, published, revision) VALUES (1, ?, ?, 0)').bind(JSON.stringify(initialContent), JSON.stringify(initialContent)).run();
  const result = await db.prepare('UPDATE portfolio_content SET draft = ?, revision = revision + 1 WHERE id = 1 AND revision = ? RETURNING revision').bind(json, revision).first<{
    revision: number;
  }>();
  if (!result) throw new Error('CONFLICT');
  return result.revision;
}
export async function publish(db: D1Database, revision: number) {
  const now = new Date().toISOString();
  const results = await db.batch([db.prepare('INSERT INTO portfolio_versions (content, created_at) SELECT draft, ? FROM portfolio_content WHERE id = 1 AND revision = ?').bind(now, revision), db.prepare('UPDATE portfolio_content SET published = draft, published_at = ?, revision = revision + 1 WHERE id = 1 AND revision = ?').bind(now, revision)]);
  if (!results[1].meta?.changes) throw new Error('CONFLICT');
  return revision + 1;
}
export async function getPublished(): Promise<Content> {
  const {
    env
  } = await import('cloudflare:workers');
  return (await load(env.CMS_DB)).published;
}
