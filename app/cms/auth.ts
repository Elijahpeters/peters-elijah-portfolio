const encoder = new TextEncoder();
export const cookieName = '__Host-portfolio-admin';
const lifeSeconds = 8 * 60 * 60;
async function key(secret: string) {
  return crypto.subtle.importKey('raw', encoder.encode(secret), {
    name: 'HMAC',
    hash: 'SHA-256'
  }, false, ['sign', 'verify']);
}
function hex(bytes: ArrayBuffer) {
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
}
export async function matchesSecret(input: string, secret: string): Promise<boolean> {
  if (secret.length < 32 || input.length > 256) return false;
  const digest = await crypto.subtle.sign('HMAC', await key(secret), encoder.encode(input));
  return crypto.subtle.verify('HMAC', await key(secret), digest, encoder.encode(secret));
}
export async function makeSession(secret: string, now = Date.now()): Promise<string> {
  const body = `${Math.floor(now / 1000) + lifeSeconds}.${crypto.randomUUID()}`;
  return `${body}.${hex(await crypto.subtle.sign('HMAC', await key(secret), encoder.encode(body)))}`;
}
export async function validSession(token: string, secret: string, now = Date.now()): Promise<boolean> {
  if (secret.length < 32 || token.length > 200) return false;
  const [expires, nonce, signature, ...rest] = token.split('.');
  if (rest.length || !/^[0-9]{10}$/.test(expires ?? '') || !/^[0-9a-f-]{36}$/.test(nonce ?? '') || !/^[0-9a-f]{64}$/.test(signature ?? '')) return false;
  const seconds = Math.floor(now / 1000);
  if (+expires <= seconds || +expires > seconds + lifeSeconds) return false;
  const bytes = Uint8Array.from(signature.match(/../g)!, v => parseInt(v, 16));
  return crypto.subtle.verify('HMAC', await key(secret), bytes, encoder.encode(`${expires}.${nonce}`));
}
export function sessionCookie(token: string, logout = false) {
  return `${cookieName}=${token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${logout ? 0 : lifeSeconds}`;
}
export async function authorized(request: Request, secret: string) {
  const token = request.headers.get('cookie')?.split(';').map(s => s.trim()).find(s => s.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1) ?? '';
  return validSession(token, secret);
}
