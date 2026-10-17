import { headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { env } from 'cloudflare:workers';
import { authorized } from '../../cms/auth';
import { load } from '../../cms/storage';
import Portfolio from '../../cms/Portfolio';
export const dynamic = 'force-dynamic';
export const metadata = {
  title: 'Private draft preview',
  robots: {
    index: false,
    follow: false
  }
};
export default async function Preview() {
  const h = await headers();
  if (!env.CMS_ADMIN_KEY || !(await authorized(new Request('https://preview.invalid', {
    headers: h
  }), env.CMS_ADMIN_KEY))) redirect('/admin');
  return <Portfolio content={(await load(env.CMS_DB)).draft} preview />;
}
