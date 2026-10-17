import {getPublished} from './cms/storage';
import {siteOrigin} from './cms/metadata';
import {publicSitemap} from './cms/sitemap';
export const dynamic='force-dynamic';
export default async function sitemap(){return publicSitemap(await getPublished(),siteOrigin);}
