// Guard against accidentally deploying the rebuild over the current portfolio.
import {spawnSync} from 'node:child_process';
for (const name of ['PORTFOLIO_CMS_D1_ID','PORTFOLIO_SKYETA_D1_ID','NEXT_PUBLIC_SITE_URL']) {
 if (!process.env[name] || process.env[name].startsWith('00000000')) throw new Error(`Configure ${name} before deploying the replacement. See README.md.`);
}
if (!/^https:\/\//.test(process.env.NEXT_PUBLIC_SITE_URL)) throw new Error('NEXT_PUBLIC_SITE_URL must be HTTPS');
for (const args of [['run','build'],['exec','wrangler','--','deploy']]) {
 const result=spawnSync('npm',args,{stdio:'inherit',env:process.env});
 if(result.status!==0)process.exit(result.status??1);
}
