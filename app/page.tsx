import { getPublished } from './cms/storage';
import { contentMetadata } from './cms/metadata';
import Portfolio from './cms/Portfolio';
export const dynamic = 'force-dynamic';
export async function generateMetadata() { return contentMetadata(await getPublished()); }
export default async function Home() { return <Portfolio content={await getPublished()}/>; }
