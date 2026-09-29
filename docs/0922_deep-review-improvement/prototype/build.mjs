// Builds a self-contained, offline prototype using installed project dependencies.
import {readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../../..');
const frontend=path.join(root,'web/frontend');
const {build}=await import(path.join(frontend,'node_modules/esbuild/lib/main.js'));
const bundle=await build({entryPoints:[path.join(here,'prototype.jsx')],bundle:true,minify:true,write:false,format:'iife',target:['chrome120'],jsx:'automatic',loader:{'.md':'text'},nodePaths:[path.join(frontend,'node_modules')],define:{'process.env.NODE_ENV':'"production"'}});
const cssPaths=['node_modules/@astryxdesign/core/src/reset.css','node_modules/@astryxdesign/core/dist/astryx.css','src/themes/bidops/bidops.css'];
const css=(await Promise.all(cssPaths.map(f=>readFile(path.join(frontend,f),'utf8')))).join('\n');
const font=await readFile(path.join(frontend,'public/fonts/PretendardVariable.woff2'));
const custom=await readFile(path.join(here,'prototype.css'),'utf8');
const js=bundle.outputFiles[0].text.replaceAll('</script','<\\/script');
const html=`<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="light"><title>BidOps · 심층검토 UI 시안</title><style>@font-face{font-family:Pretendard;src:url(data:font/woff2;base64,${font.toString('base64')}) format('woff2');font-weight:100 900;font-display:swap;}\n${css}\n${custom}</style></head><body><div id="root"></div><script>${js}</script></body></html>`;
await writeFile(path.join(here,'index.html'),html);
console.log(JSON.stringify({artifact:path.join(here,'index.html'),bytes:Buffer.byteLength(html),network:'none',data:'fictional fixtures only'}));
