import { Buffer } from 'node:buffer';
import { authorized, matchesSecret, makeSession, sessionCookie } from './auth.ts';
import { load, saveDraft, publish } from './storage.ts';
import { validateContent } from './content.ts';
export type MediaBucket = {
  put(key: string, value: ArrayBuffer, options: {
    httpMetadata: {
      contentType: string;
    };
  }): Promise<unknown>;
  get(key: string): Promise<{
    body: ReadableStream;
    httpMetadata?: {
      contentType?: string;
    };
  } | null>;
};
export type CmsEnv = {
  CMS_DB?: D1Database;
  CMS_MEDIA?: MediaBucket;
  CMS_ADMIN_KEY?: string;
};
function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return Response.json(body, {
    status,
    headers: {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      ...headers
    }
  });
}
async function boundedBody(request: Request, limit: number) {
  if (Number(request.headers.get('content-length')) > limit) throw new Error('Request too large');
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const {
        done,
        value
      } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > limit) {
        await reader.cancel();
        throw new Error('Request too large');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.length;
  }
  return body;
}
export async function handleCms(request: Request, env: CmsEnv): Promise<Response> {
  const path = new URL(request.url).pathname.replace('/api/cms/', '');
  if (path.startsWith('media/') && request.method === 'GET') {
    const key = path.slice(6);
    if (!/^[0-9a-f-]{36}\.(png|jpg|webp|pdf)$/.test(key)) return new Response('Not found', {
      status: 404
    });
    const stored = env.CMS_DB ? await env.CMS_DB.prepare('SELECT content_type, data FROM portfolio_media WHERE key = ?').bind(key).first<{content_type: string; data: string}>() : null;
    const object = stored ? {body: Buffer.from(stored.data, 'base64'), httpMetadata: {contentType: stored.content_type}} : await env.CMS_MEDIA?.get(key);
    if (!object) return new Response('Not found', {
      status: 404
    });
    return new Response(object.body, {
      headers: {
        'Content-Type': object.httpMetadata?.contentType ?? 'application/octet-stream',
        'X-Content-Type-Options': 'nosniff',
        'Cache-Control': 'public, max-age=31536000, immutable',
        'Content-Security-Policy': "default-src 'none'; sandbox"
      }
    });
  }
  if (!env.CMS_DB || !env.CMS_ADMIN_KEY || env.CMS_ADMIN_KEY.length < 32) return json({
    error: 'Dashboard is not configured. See the README launch checklist.'
  }, 503);
  const db = env.CMS_DB;
  if (request.method !== 'GET' && request.headers.get('origin') !== new URL(request.url).origin) return json({
    error: 'Cross-origin request rejected'
  }, 403);
  try {
    if (path === 'login' && request.method === 'POST') {
      const now = Math.floor(Date.now() / 1000);
      const ip = request.headers.get('CF-Connecting-IP') ?? 'local';
      // Hash address before storing; bounded 15-minute windows. Cloudflare sets this header.
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip))), b => b.toString(16).padStart(2, '0')).join('');
      const bucket = `${hash}:${Math.floor(now / 900)}`;
      await db.prepare('DELETE FROM portfolio_login_limits WHERE expires < ?').bind(now).run();
      const attempts = await db.prepare('INSERT INTO portfolio_login_limits (bucket, attempts, expires) VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET attempts = attempts + 1 RETURNING attempts').bind(bucket, now + 900).first<{
        attempts: number;
      }>();
      if (!attempts || attempts.attempts > 10) return json({
        error: 'Too many sign-in attempts. Try again in 15 minutes.'
      }, 429, {
        'Retry-After': '900'
      });
      const body = JSON.parse(new TextDecoder().decode(await boundedBody(request, 1024)));
      if (typeof body.key !== 'string' || !(await matchesSecret(body.key, env.CMS_ADMIN_KEY))) return json({
        error: 'Incorrect access key'
      }, 401);
      return json({
        ok: true
      }, 200, {
        'Set-Cookie': sessionCookie(await makeSession(env.CMS_ADMIN_KEY))
      });
    }
    if (!(await authorized(request, env.CMS_ADMIN_KEY))) return json({
      error: 'Sign in to continue'
    }, 401);
    if (path === 'logout' && request.method === 'POST') return json({
      ok: true
    }, 200, {
      'Set-Cookie': sessionCookie('', true)
    });
    if (path === 'content' && request.method === 'GET') return json({...await load(db), uploadLimit: (env.CMS_MEDIA ? 8 : 1) * 1024 * 1024});
    if (path === 'versions' && request.method === 'GET') return json((await db.prepare('SELECT id, created_at FROM portfolio_versions ORDER BY id DESC LIMIT 50').all()).results ?? []);
    if (path === 'upload' && request.method === 'POST') {
      const limit = (env.CMS_MEDIA ? 8 : 1) * 1024 * 1024;
      let body: Uint8Array;
      try { body = await boundedBody(request, limit); }
      catch (error) {
        if (error instanceof Error && error.message === 'Request too large') return json({error: `Choose a file no larger than ${limit / 1024 / 1024} MB.`}, 413);
        throw error;
      }
      const type = request.headers.get('content-type') ?? '';
      const head = [...body.slice(0, 12)];
      const ascii = new TextDecoder().decode(body.slice(0, 12));
      const extension = type === 'image/png' && head.slice(0, 8).join(',') === '137,80,78,71,13,10,26,10' ? 'png' : type === 'image/jpeg' && head[0] === 255 && head[1] === 216 && head[2] === 255 ? 'jpg' : type === 'image/webp' && ascii.startsWith('RIFF') && ascii.slice(8) === 'WEBP' ? 'webp' : type === 'application/pdf' && ascii.startsWith('%PDF-') ? 'pdf' : null;
      if (!extension) return json({
        error: 'Upload a valid PNG, JPEG, WebP or PDF.'
      }, 400);
      const key = `${crypto.randomUUID()}.${extension}`;
      if (env.CMS_MEDIA) await env.CMS_MEDIA.put(key, body.buffer as ArrayBuffer, {
        httpMetadata: {
          contentType: type
        }
      });
      else await db.prepare('INSERT INTO portfolio_media (key, content_type, data, size) VALUES (?, ?, ?, ?)').bind(key, type, Buffer.from(body).toString('base64'), body.byteLength).run();
      return json({
        url: `/api/cms/media/${key}`
      }, 201);
    }
    if (request.method === 'POST' && ['content', 'publish', 'restore'].includes(path)) {
      const body = JSON.parse(new TextDecoder().decode(await boundedBody(request, 512 * 1024)));
      if (!Number.isSafeInteger(body.revision) || body.revision < 0) return json({
        error: 'Invalid revision'
      }, 400);
      if (path === 'content') return json({
        revision: await saveDraft(db, validateContent(body.content), body.revision)
      });
      if (path === 'publish') return json({
        revision: await publish(db, body.revision)
      });
      if (!Number.isSafeInteger(body.id)) return json({
        error: 'Invalid version'
      }, 400);
      const row = await db.prepare('SELECT content FROM portfolio_versions WHERE id = ?').bind(body.id).first<{
        content: string;
      }>();
      if (!row) return json({
        error: 'Version not found'
      }, 404);
      return json({
        revision: await saveDraft(db, validateContent(JSON.parse(row.content)), body.revision)
      });
    }
    return json({
      error: 'Not found'
    }, 404);
  } catch (error) {
    if (error instanceof Error && error.message === 'CONFLICT') return json({
      error: 'The content changed in another session. Reload before saving.'
    }, 409);
    if (error instanceof Error && error.message.includes('MEDIA_CAPACITY')) return json({error: 'Media storage is full. Contact the site maintainer to expand storage.'}, 507);
    if (error instanceof SyntaxError) return json({
      error: 'Invalid JSON'
    }, 400);
    // Never return database/provider details or secrets to the browser.
    if (error instanceof Error && /expected|field|required|valid contact|HTTPS|unique lowercase|Project title|Unsafe|Request too large|Invalid design|Invalid colour|Colour contrast|Sections need|Invalid section|Only one|introduction must|Standard section/.test(error.message)) return json({
      error: error.message
    }, 400);
    console.error('CMS operation failed');
    return json({
      error: 'Content storage is unavailable. Your published content has not been replaced. Check the CMS migration and bindings.'
    }, 503);
  }
}
