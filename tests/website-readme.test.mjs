import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const source = await readFile(new URL('../app/readme/ReadmeContent.tsx', import.meta.url), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const context = { exports: {}, require };
vm.runInNewContext(output, context);
const { default: ReadmeContent, readmeLink, headingAnchor } = context.exports;
const html = text => renderToStaticMarkup(createElement(ReadmeContent, { source: text }));

test('website README renders the actual project explanations and matching overview anchors', async () => {
  const readme = await readFile(new URL('../README.md', import.meta.url), 'utf8');
  const markup = html(readme);
  assert.equal((markup.match(/<h1\b/g) ?? []).length, 1);
  assert.equal((markup.match(/1\. What problem does it solve\?/g) ?? []).length, 3);
  assert.equal((markup.match(/6\. What assumptions and trade-offs did I make\?/g) ?? []).length, 3);
  for (const title of ['SkyETA — flight search with honest delay evidence', 'AuraPass — offline exam access control', 'Incubator carrier board and circuit studies']) {
    assert.ok(markup.includes(`id="${headingAnchor(title)}"`));
    assert.ok(markup.includes(`href="#${headingAnchor(title)}"`));
  }
  assert.match(markup, /not yet bench-tested/);
  assert.match(markup, /5,000/);
  assert.match(markup, /0\.61/);
  assert.match(markup, /scope="col"/);
});

test('README links resolve public evidence locally and source code to GitHub', () => {
  assert.equal(readmeLink('public/assets/Peters-Elijah-CV.pdf'), '/assets/Peters-Elijah-CV.pdf');
  assert.equal(readmeLink('app/skyeta'), 'https://github.com/Elijahpeters/peters-elijah-portfolio/blob/main/app/skyeta');
  assert.equal(readmeLink('#skyeta'), '#skyeta');
  assert.equal(readmeLink('/projects/aurapass'), '/projects/aurapass');
  assert.equal(readmeLink('javascript:alert(1)'), undefined);
  assert.equal(readmeLink('//untrusted.example'), undefined);
});

test('README rendering escapes HTML and does not execute embedded markup', () => {
  const markup = html('# Guide\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert)\n\n**Evidence** and `code`');
  assert.doesNotMatch(markup, /<script|href="javascript:/);
  assert.match(markup, /&lt;script&gt;/);
  assert.match(markup, /<strong>Evidence<\/strong>/);
  assert.match(markup, /<code>code<\/code>/);
});
