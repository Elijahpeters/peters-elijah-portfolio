import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Exercise the component's event handlers and effect lifecycle with a fake clock.
// No network, browser globals, or production timers are used.
async function setup() {
  let cursor = 0, now = 0, nextTimer = 0;
  const slots = [], effects = [], timers = new Map(), listeners = new Map();
  const react = {
    useState(value) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = value;
      return [slots[index], next => { slots[index] = next; }];
    },
    useRef(value) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: value };
      return slots[index];
    },
    useEffect(callback, deps) {
      const index = cursor++;
      const previous = effects[index];
      if (!previous || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
        previous?.cleanup?.();
        effects[index] = { deps, callback, pending: true };
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const source = await readFile(new URL('../app/components/WorkIntroduction.tsx', import.meta.url), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const context = {
    exports: {},
    require: name => name === 'react' ? react : name === 'react/jsx-runtime' ? { jsx, jsxs: jsx } : { default: { attention: 'attention', panel: 'panel' } },
    document: { activeElement: null, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) },
    window: {
      setTimeout: (fn, delay) => { timers.set(++nextTimer, { fn, at: now + delay }); return nextTimer; },
      clearTimeout: id => timers.delete(id),
      requestAnimationFrame: fn => fn(),
    },
  };
  vm.runInNewContext(output, context);
  function render() {
    cursor = 0;
    const tree = context.exports.default();
    for (const effect of effects) if (effect?.pending) { effect.pending = false; effect.cleanup = effect.callback(); }
    return tree;
  }
  return {
    render,
    advance(ms) { now += ms; for (const [id, timer] of timers) if (timer.at <= now) { timers.delete(id); timer.fn(); } },
    escape() { listeners.get('keydown')?.({ key: 'Escape' }); },
    unmount() { effects.forEach(effect => effect?.cleanup?.()); },
    get pendingTimers() { return timers.size; },
  };
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  const children = [tree.props?.children].flat(Infinity);
  for (const child of children) { const match = find(child, predicate); if (match) return match; }
}

test('introduction opens immediately and reminds once at ten seconds', async () => {
  const ui = await setup();
  assert.equal(ui.render().type, 'aside');
  ui.advance(9999);
  assert.doesNotMatch(ui.render().props.className, /attention/);
  ui.advance(1);
  assert.match(ui.render().props.className, /attention/);
  assert.equal(ui.pendingTimers, 0);
  ui.advance(60000);
  assert.equal(ui.pendingTimers, 0);
});

test('pointer or keyboard engagement cancels the unattended reminder', async () => {
  for (const event of ['onPointerEnter', 'onPointerDown', 'onFocusCapture']) {
    const ui = await setup();
    ui.render().props[event]();
    ui.render();
    ui.advance(10000);
    assert.doesNotMatch(ui.render().props.className, /attention/);
    assert.equal(ui.pendingTimers, 0);
  }
});

test('X and Escape dismiss, and the visitor can reopen without another reminder', async () => {
  for (const method of ['close', 'escape']) {
    const ui = await setup();
    const panel = ui.render();
    if (method === 'close') find(panel, n => n.props?.['aria-label'] === 'Close introduction').props.onClick();
    else ui.escape();
    const button = ui.render();
    assert.equal(button.type, 'button');
    assert.equal(ui.pendingTimers, 0);
    button.props.onClick();
    assert.equal(ui.render().type, 'aside');
    assert.equal(ui.pendingTimers, 0);
  }
});

test('following a project link closes the panel and unmount cancels timers', async () => {
  const ui = await setup();
  find(ui.render(), n => n.props?.href === '#projects').props.onClick();
  assert.equal(ui.render().type, 'button');
  const fresh = await setup();
  fresh.render();
  fresh.unmount();
  assert.equal(fresh.pendingTimers, 0);
});
