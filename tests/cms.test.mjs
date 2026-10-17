import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import {initialContent,validateContent} from '../app/cms/content.ts';
import {makeSession,validSession,matchesSecret,sessionCookie} from '../app/cms/auth.ts';
import {load,saveDraft,publish} from '../app/cms/storage.ts';
import {handleCms} from '../app/cms/api.ts';
import {contentMetadata,personSchema} from '../app/cms/metadata.ts';
import {publicSitemap} from '../app/cms/sitemap.ts';
const secret='a'.repeat(64);
const copy=()=>structuredClone(initialContent);
async function database(){
 const sql=new DatabaseSync(':memory:');sql.exec(await readFile(new URL('../db/migrations/portfolio-cms.sql',import.meta.url),'utf8'));
 const db={prepare(query){let values=[];return {bind(...v){values=v;return this;},async first(){return sql.prepare(query).get(...values)??null;},async all(){return {results:sql.prepare(query).all(...values)};},async run(){const r=sql.prepare(query).run(...values);return {success:true,meta:{changes:r.changes}};}};},async batch(statements){sql.exec('BEGIN');try{const result=[];for(const s of statements)result.push(await s.run());sql.exec('COMMIT');return result;}catch(e){sql.exec('ROLLBACK');throw e;}},close(){sql.close();}};return db;
}
function request(path,body,cookie,origin='https://portfolio.example'){return new Request(`https://portfolio.example/api/cms/${path}`,{method:body===undefined?'GET':'POST',headers:{...(body!==undefined?{'Content-Type':'application/json',Origin:origin}:{}),...(cookie?{Cookie:cookie}:{})},body:body===undefined?undefined:JSON.stringify(body)});}
test('content defaults preserve identity, project validation boundaries and new portrait',()=>{assert.deepEqual(validateContent(copy()),initialContent);assert.equal(initialContent.profile.fullName,'Peters Elijah Temidayo');assert.equal(initialContent.profile.alternateName,'Elijah Peters');assert.match(initialContent.profile.portrait,/elijah-portrait-2026/);assert.match(initialContent.projects[2].status,/not bench-tested/);assert.equal(initialContent.circuits.length,5);});
test('validator rejects executable URLs, duplicate slugs, invalid themes and invisible introduction',()=>{for(const mutate of [c=>c.profile.portrait='javascript:alert(1)',c=>c.projects[0].slug=c.projects[1].slug,c=>c.design.colors.ink=c.design.colors.paper,c=>c.design.width='9000',c=>c.design.sections[0].visible='no',c=>c.design.sections.push({...c.design.sections[0]}),c=>c.projects[0].sourceUrl='https://user:pass@example.com',c=>c.design.sections[1].id='bad id']){const c=copy();mutate(c);assert.throws(()=>validateContent(c));}});
test('session is signed, expires, cannot be forged and requires a high-entropy length key',async()=>{const token=await makeSession(secret);assert.ok(await validSession(token,secret));assert.equal(await validSession(token,secret+'x'),false);assert.equal(await validSession(token,secret,Date.now()+9*3600000),false);assert.equal(await validSession(token.slice(0,-1)+'z',secret),false);assert.equal(await validSession('bad',secret),false);assert.equal(await matchesSecret(secret,secret),true);assert.equal(await matchesSecret('wrong',secret),false);assert.equal(await matchesSecret('short','short'),false);assert.match(sessionCookie(token),/HttpOnly; Secure; SameSite=Strict/);});
test('drafts stay private, publish changes public content, stale writes cannot overwrite it',async()=>{const db=await database();try{let state=await load(db);assert.equal(state.revision,0);const c=copy();c.profile.headline='A changed introduction';assert.equal(await saveDraft(db,c,0),1);state=await load(db);assert.equal(state.published.profile.headline,initialContent.profile.headline);assert.equal(state.draft.profile.headline,c.profile.headline);await assert.rejects(saveDraft(db,copy(),0),/CONFLICT/);assert.equal(await publish(db,1),2);assert.equal((await load(db)).published.profile.headline,c.profile.headline);await assert.rejects(publish(db,1),/CONFLICT/);assert.equal((await db.prepare('SELECT * FROM portfolio_versions').all()).results.length,1);}finally{db.close();}});
test('API fails closed, enforces session and origin, rate-limits sign-in, and restores drafts only',async()=>{const db=await database();try{const env={CMS_DB:db,CMS_ADMIN_KEY:secret};assert.equal((await handleCms(request('content'),{})).status,503);assert.equal((await handleCms(request('content'),env)).status,401);assert.equal((await handleCms(request('login',{key:secret},null,'https://evil.example'),env)).status,403);const login=await handleCms(request('login',{key:secret}),env);assert.equal(login.status,200);const cookie=login.headers.get('set-cookie').split(';')[0];const c=copy();c.profile.headline='Published version';let result=await handleCms(request('content',{content:c,revision:0},cookie),env);assert.equal(result.status,200);result=await handleCms(request('publish',{revision:1},cookie),env);assert.equal(result.status,200);c.profile.headline='Second version';await handleCms(request('content',{content:c,revision:2},cookie),env);await handleCms(request('publish',{revision:3},cookie),env);result=await handleCms(request('restore',{id:1,revision:4},cookie),env);assert.equal(result.status,200);const state=await load(db);assert.equal(state.draft.profile.headline,'Published version');assert.equal(state.published.profile.headline,'Second version');for(let i=0;i<10;i++)result=await handleCms(request('login',{key:'wrong'}),env);assert.equal(result.status,429);}finally{db.close();}});
test('uploads require auth, enforce signatures and size, and expose immutable files only',async()=>{const db=await database();try{const saved=new Map();const env={CMS_DB:db,CMS_ADMIN_KEY:secret,CMS_MEDIA:{async put(k,v,options){saved.set(k,{body:v,httpMetadata:options.httpMetadata});},async get(k){return saved.get(k);}}};const cookie=sessionCookie(await makeSession(secret)).split(';')[0];const upload=(bytes,type,c=cookie)=>new Request('https://portfolio.example/api/cms/upload',{method:'POST',headers:{Origin:'https://portfolio.example',Cookie:c,'Content-Type':type},body:bytes});assert.equal((await handleCms(upload('<script/>','image/png'),env)).status,400);assert.equal((await handleCms(upload(new Uint8Array(8*1024*1024+1),'image/png'),env)).status,413);assert.equal((await handleCms(upload('%PDF-1.7','application/pdf',''),env)).status,401);const r=await handleCms(upload('%PDF-1.7','application/pdf'),env);assert.equal(r.status,201);const {url}=await r.json();const publicFile=await handleCms(new Request(`https://portfolio.example${url}`),env);assert.equal(publicFile.status,200);assert.equal(publicFile.headers.get('content-type'),'application/pdf');assert.match(publicFile.headers.get('content-security-policy'),/sandbox/);}finally{db.close();}});
test('SEO uses published content; sitemap includes CMS projects but excludes private routes',()=>{const c=copy();const meta=contentMetadata(c);assert.equal(meta.description,c.seo.description);assert.equal(meta.openGraph.description,meta.description);assert.equal(meta.twitter.title,meta.title);assert.equal(personSchema(c).alternateName,'Elijah Peters');assert.deepEqual(personSchema(c).sameAs,[c.profile.linkedin,c.profile.github]);c.projects.push({...c.projects[0],slug:'new-project',title:'New project'});const urls=publicSitemap(c,'https://portfolio.example').map(p=>p.url);assert.ok(urls.includes('https://portfolio.example/work/new-project'));assert.ok(urls.includes('https://portfolio.example/work/antoniou-gic'));assert.ok(urls.every(url=>!url.includes('/admin')&&!url.includes('/api/')));});
test('database media round-trips binary bytes without R2 and enforces limits', async()=>{
 const db=await database();
 try {
  const env={CMS_DB:db,CMS_ADMIN_KEY:secret};
  const cookie=sessionCookie(await makeSession(secret)).split(';')[0];
  const upload=(body,c=cookie)=>new Request('https://portfolio.example/api/cms/upload',{method:'POST',headers:{Origin:'https://portfolio.example',Cookie:c,'Content-Type':'image/png'},body});
  const bytes=new Uint8Array([137,80,78,71,13,10,26,10,0,255,128,1]);
  assert.equal((await handleCms(upload(bytes,''),env)).status,401);
  assert.equal((await handleCms(upload('invalid'),env)).status,400);
  assert.equal((await handleCms(upload(new Uint8Array(1048577)),env)).status,413);
  const r=await handleCms(upload(bytes),env);assert.equal(r.status,201);
  const {url}=await r.json();
  for(const config of [env,{...env,CMS_MEDIA:{get:async()=>null}}]) {
   const file=await handleCms(new Request('https://portfolio.example'+url),config);
   assert.equal(file.status,200);assert.equal(file.headers.get('content-type'),'image/png');
   assert.deepEqual(new Uint8Array(await file.arrayBuffer()),bytes);
  }
  const settings=await handleCms(request('content',undefined,cookie),env);
  assert.equal((await settings.json()).uploadLimit,1048576);
  // Fill accounting rows to one file below capacity, without allocating 100 MiB in the test.
  for(let i=0;i<99;i++) await db.prepare('INSERT INTO portfolio_media (key,content_type,data,size) VALUES (?,?,?,?)').bind('capacity-'+i,'image/png','',1048576).run();
  const last=new Uint8Array(1048576-bytes.length);last.set(bytes);
  assert.equal((await handleCms(upload(last),env)).status,201);
  assert.equal((await handleCms(upload(bytes),env)).status,507);
  assert.equal((await db.prepare('SELECT SUM(size) AS total FROM portfolio_media').first()).total,104857600);
 } finally {db.close();}
});
