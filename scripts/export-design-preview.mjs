/** Export the real React homepage as a standalone, non-interactive review file. */
import {build} from 'esbuild';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd();const output=resolve(root,'outputs');await mkdir(output,{recursive:true});
await build({stdin:{contents:`import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import Portfolio from './app/cms/Portfolio';import {initialContent} from './app/cms/content';import './app/globals.css';export const html=renderToStaticMarkup(React.createElement(Portfolio,{content:initialContent}));`,resolveDir:root,loader:'tsx'},bundle:true,platform:'node',format:'esm',packages:'external',jsx:'automatic',outfile:resolve(output,'preview-render.mjs'),plugins:[{name:'unoptimized-review-images',setup(b){b.onResolve({filter:/^next\/image$/},()=>({path:'image',namespace:'review'}));b.onLoad({filter:/.*/,namespace:'review'},()=>({contents:`import React from 'react';export default function Image({src,alt,width,height,className}){return React.createElement('img',{src,alt,width,height,className});}`,loader:'js',resolveDir:root}));}}]});
let {html}=await import(pathToFileURL(resolve(output,'preview-render.mjs')));
const mime={'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'};
for(const path of new Set([...html.matchAll(/(?:src|href)="(\/assets\/[^"?#]+\.(?:png|jpg|webp))"/g)].map(m=>m[1]))){const body=await readFile(resolve(root,'public'+path));html=html.replaceAll(path,`data:${mime[extname(path)]};base64,${body.toString('base64')}`);}
const css=await readFile(resolve(output,'preview-render.css'),'utf8');
const notice='<div style="background:#f3df9f;color:#33280b;padding:12px 24px;font:14px Arial;text-align:center">Design review — the contact form and project links require the running application. This is not the live site.</div>';
const document=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Elijah Peters — new portfolio design review</title><style>${css}</style></head><body>${notice}${html}<script>const menu=document.querySelector('[aria-controls=portfolio-navigation]');if(menu)menu.addEventListener('click',()=>{const expanded=menu.getAttribute('aria-expanded')==='true';menu.setAttribute('aria-expanded',String(!expanded));document.getElementById('portfolio-navigation').style.display=expanded?'':'flex';});document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();alert('This is a design preview. Contact is available in the running application.')}));document.querySelectorAll('a[href^="/"]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();alert('Open this project in the running portfolio application.')}));</script></body></html>`;
await writeFile(resolve(root,'docs/portfolio-design-preview.html'),document);
await writeFile(resolve(output,'rendered-home.html'),html);
console.log('Exported docs/portfolio-design-preview.html');
