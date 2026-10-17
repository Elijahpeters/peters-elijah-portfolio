import { env } from 'cloudflare:workers';
import { handleCms } from '../../../cms/api';
export const dynamic = 'force-dynamic';
export function GET(request: Request) {
  return handleCms(request, env);
}
export function POST(request: Request) {
  return handleCms(request, env);
}
