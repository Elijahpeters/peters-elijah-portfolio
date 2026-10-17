'use client';

import { useRef, useEffect } from 'react';
import { initialContent, type Design, type Section } from '../cms/content';
import styles from './admin.module.css';
const palettes = [{
  name: 'Sage & graphite',
  colors: initialContent.design.colors
}, {
  name: 'Navy & ivory',
  colors: {
    paper: '#faf8f2',
    ink: '#172740',
    muted: '#4d5b70',
    surface: '#eeeee8',
    line: '#c0c5ca',
    accent: '#d6dded',
    buttonText: '#ffffff'
  }
}, {
  name: 'Warm editorial',
  colors: {
    paper: '#faf5ec',
    ink: '#3b2a24',
    muted: '#67584c',
    surface: '#f0e6d8',
    line: '#cabbab',
    accent: '#e7c795',
    buttonText: '#ffffff'
  }
}, {
  name: 'Midnight',
  colors: {
    paper: '#101e24',
    ink: '#e6eee8',
    muted: '#b2c1b7',
    surface: '#1c3037',
    line: '#46615d',
    accent: '#233a32',
    buttonText: '#102127'
  }
}];
export default function Designer({
  value: d,
  onChange,
  onMessage
}: {
  value: Design;
  onChange: (d: Design) => void;
  onMessage: (message: string) => void;
}) {
  const latest = useRef(d);
  useEffect(() => {
    latest.current = d;
  }, [d]);
  const set = (key: keyof Design, value: unknown) => onChange({
    ...d,
    [key]: value
  });
  const update = (index: number, patch: Partial<Section>) => set('sections', d.sections.map((s, i) => i === index ? {
    ...s,
    ...patch
  } : s));
  const move = (index: number, by: number) => {
    const next = [...d.sections];
    [next[index], next[index + by]] = [next[index + by], next[index]];
    set('sections', next);
  };
  return <div className={styles.designer}>
 <fieldset><legend>Colour palettes</legend><p>Start with a palette, then adjust individual colours. Publishing checks text contrast.</p><div className={styles.palettes}>{palettes.map(p => <button type="button" key={p.name} onClick={() => set('colors', p.colors)}><span className={styles.swatches}>{Object.values(p.colors).slice(0, 4).map((color, i) => <i key={i} style={{
              background: color
            }} />)}</span>{p.name}</button>)}</div><div className={styles.colorGrid}>{Object.entries(d.colors).map(([name, color]) => <label key={name}>{({
            paper: 'Page background',
            ink: 'Main text / strong backgrounds',
            muted: 'Secondary text',
            surface: 'Cards / panels',
            line: 'Borders',
            accent: 'Accent',
            buttonText: 'Text on strong backgrounds'
          } as Record<string, string>)[name]}<div><input type="color" value={color} onChange={e => set('colors', {
              ...d.colors,
              [name]: e.target.value
            })} /><input aria-label={`${name} hex colour`} value={color} maxLength={7} onChange={e => set('colors', {
              ...d.colors,
              [name]: e.target.value
            })} /></div></label>)}</div></fieldset>
 <fieldset><legend>Typography & layout</legend><div className={styles.settingsGrid}>{[['typography', 'Type style', [['modern', 'Modern sans serif'], ['editorial', 'Editorial serif'], ['technical', 'Technical monospace']]], ['heroLayout', 'Introduction layout', [['split', 'Text left, portrait right'], ['portrait-left', 'Portrait left, text right'], ['stacked', 'Centred & stacked'], ['text-only', 'Text only']]], ['projectLayout', 'Project layout', [['rows', 'Large project rows'], ['cards', 'Two-column cards']]]].map(([key, label, options]) => <label key={key as string}>{label as string}<select value={d[key as keyof Design] as string} onChange={e => set(key as keyof Design, e.target.value)}>{(options as string[][]).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>)}</div>{[['spacing', 'Section spacing', 32, 104], ['radius', 'Corner rounding', 0, 32], ['width', 'Content width', 960, 1440]].map(([key, label, min, max]) => <label className={styles.slider} key={key}>{label}: {d[key as keyof Design] as string}px<input type="range" min={min} max={max} step={key === 'width' ? 20 : 1} value={d[key as keyof Design] as string} onChange={e => set(key as keyof Design, e.target.value)} /></label>)}</fieldset>
 <fieldset><legend>Page structure</legend><p>Move sections to change the reading order. Hide sections without deleting their content. Add text, image or callout sections below.</p><div className={styles.list}>{d.sections.map((s, i) => <details key={s.id} className={styles.structure}><summary>{i + 1}. {s.label || s.type} {s.visible === 'no' ? '(hidden)' : ''}</summary><div className={styles.itemActions}><button type="button" disabled={i === 0} onClick={() => move(i, -1)}>↑ Move up</button><button type="button" disabled={i === d.sections.length - 1} onClick={() => move(i, 1)}>↓ Move down</button><button type="button" disabled={s.type === 'hero'} onClick={() => update(i, {
              visible: s.visible === 'yes' ? 'no' : 'yes'
            })}>{s.visible === 'yes' ? 'Hide' : 'Show'}</button>{s.type === 'custom' && <button type="button" onClick={() => {
              if (window.confirm('Remove this custom section from the draft?')) set('sections', d.sections.filter((_, n) => n !== i));
            }}>Remove</button>}</div><div className={styles.fields}><label>Navigation label<input value={s.label} onChange={e => update(i, {
                label: e.target.value
              })} /></label>{s.type !== 'hero' && s.type !== 'contact' && <><label>Heading<input value={s.heading} onChange={e => update(i, {
                  heading: e.target.value
                })} /></label><label>Supporting text<textarea value={s.text} onChange={e => update(i, {
                  text: e.target.value
                })} /></label></>}{s.type === 'custom' && <><label>Section address<input value={s.id} onChange={e => update(i, {
                  id: e.target.value
                })} /></label><label>Layout<select value={s.layout} onChange={e => update(i, {
                  layout: e.target.value
                })}><option value="text">Text</option><option value="image-left">Image left</option><option value="image-right">Image right</option><option value="callout">Highlighted callout</option></select></label><label>Image URL<input value={s.image} onChange={e => update(i, {
                  image: e.target.value
                })} /></label><label className={styles.upload}>Upload section image<input type="file" accept="image/png,image/jpeg,image/webp" onChange={async e => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  try {
                    if (file.size > 8 * 1024 * 1024) throw new Error('Choose an image below 8 MB');
                    onMessage('Uploading image…');
                    const response = await fetch('/api/cms/upload', {
                      method: 'POST',
                      headers: {
                        'Content-Type': file.type
                      },
                      body: file
                    });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.error);
                    onChange({
                      ...latest.current,
                      sections: latest.current.sections.map(section => section.id === s.id ? {
                        ...section,
                        image: result.url
                      } : section)
                    });
                    onMessage('Image uploaded. Save the draft when ready.');
                  } catch (error) {
                    onMessage(error instanceof Error ? error.message : 'Upload failed');
                  } finally {
                    e.target.value = '';
                  }
                }} /></label><label>Image description<input value={s.imageAlt} onChange={e => update(i, {
                  imageAlt: e.target.value
                })} /></label><label>Button label<input value={s.buttonLabel} onChange={e => update(i, {
                  buttonLabel: e.target.value
                })} /></label><label>Button destination<input value={s.buttonUrl} onChange={e => update(i, {
                  buttonUrl: e.target.value
                })} /></label></>}</div></details>)}</div><button type="button" className={styles.add} disabled={d.sections.length >= 40} onClick={() => set('sections', [...d.sections, {
        id: `section-${crypto.randomUUID().slice(0, 8)}`,
        type: 'custom',
        visible: 'yes',
        label: 'New section',
        heading: 'A new section',
        text: 'Add your text here.',
        image: '',
        imageAlt: '',
        buttonLabel: '',
        buttonUrl: '',
        layout: 'text'
      }])}>+ Add custom section</button></fieldset>
 </div>;
}
