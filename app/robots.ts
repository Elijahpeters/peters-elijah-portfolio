import type {MetadataRoute} from 'next';
import {siteOrigin} from './cms/metadata';
export default function robots():MetadataRoute.Robots {return {rules:{userAgent:'*',allow:'/',disallow:['/admin','/api/cms']},sitemap:`${siteOrigin}/sitemap.xml`};}
