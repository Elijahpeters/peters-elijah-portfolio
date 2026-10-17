/* eslint-disable @next/next/no-html-link-for-pages -- Full navigations load the latest published CMS revision. */
'use client';

import { useState, useEffect, useRef, type FormEvent } from 'react';
import { initialContent, validateContent, type Content } from '../cms/content';
import type { Snapshot } from '../cms/storage';
import Designer from './Designer';
import styles from './admin.module.css';
const sections: {
  key: keyof Content;
  label: string;
  description: string;
}[] = [{
  key: 'design',
  label: 'Design & structure',
  description: 'Change the palette, typography, layouts and section order. Preview before publishing.'
}, {
  key: 'profile',
  label: 'Profile & contact',
  description: 'Your identity, introduction, portrait, CV and professional links.'
}, {
  key: 'circuits',
  label: 'Circuit studies',
  description: 'Schematics, design reasoning, evidence and limitations.'
}, {
  key: 'projects',
  label: 'Projects',
  description: 'Project cards and case-study text. Keep claims and validation status accurate.'
}, {
  key: 'capabilities',
  label: 'What I build',
  description: 'The engineering work you want recruiters to understand first.'
}, {
  key: 'experience',
  label: 'Experience',
  description: 'Roles, organisations, dates and concise descriptions of your work.'
}, {
  key: 'skills',
  label: 'Technical skills',
  description: 'Organise tools and techniques into readable groups.'
}, {
  key: 'seo',
  label: 'Search & sharing',
  description: 'Homepage title, description and social-sharing image.'
}];
const labels: Record<string, string> = {
  brand: 'Header & footer name',
  fullName: 'Formal / full name',
  alternateName: 'Professional name',
  role: 'Professional title',
  headline: 'Homepage headline',
  introduction: 'Introduction',
  location: 'Location',
  portrait: 'Portrait image',
  portraitAlt: 'Portrait description (accessibility)',
  cv: 'CV PDF',
  about: 'About you',
  email: 'Contact email',
  phone: 'Phone number',
  github: 'GitHub profile',
  linkedin: 'LinkedIn profile',
  contactHeading: 'Contact heading',
  contactText: 'Contact introduction',
  title: 'Title',
  description: 'Description',
  image: 'Image',
  imageAlt: 'Image description (accessibility)',
  slug: 'Page address (slug)',
  category: 'Category',
  status: 'Validation / development status',
  summary: 'Summary',
  tools: 'Tools & technologies',
  evidenceUrl: 'Technical evidence link',
  sourceUrl: 'Source code link',
  demoUrl: 'Application link',
  sections: 'Case-study sections',
  heading: 'Section heading',
  text: 'Text',
  company: 'Organisation',
  period: 'Period'
};
const fileFields = new Set(['portrait', 'image', 'cv']);
function emptyLike(value: unknown): unknown {
  if (typeof value === 'string') return '';
  if (Array.isArray(value)) return [];
  return Object.fromEntries(Object.entries(value as object).map(([key, v]) => [key, emptyLike(v)]));
}
function Fields({
  value,
  sample,
  onChange,
  path,
  onMessage,
  uploadLimit
}: {
  value: unknown;
  sample: unknown;
  onChange: (v: unknown) => void;
  path: string;
  onMessage: (v: string) => void;
  uploadLimit: number;
}) {
  const [uploading, setUploading] = useState(false);
  const latestValue = useRef(value);
  useEffect(() => {
    latestValue.current = value;
  }, [value]);
  if (Array.isArray(value)) return <div className={styles.list}>{value.map((item, i) => <fieldset className={styles.item} key={`${path}-${i}`}><legend>{(item as {
          title?: string;
          role?: string;
          heading?: string;
        }).title || (item as {
          role?: string;
        }).role || (item as {
          heading?: string;
        }).heading || `Item ${i + 1}`}</legend><div className={styles.itemActions}><button type="button" disabled={i === 0} aria-label={`Move item ${i + 1} up`} onClick={() => {
          const next = [...value];
          [next[i - 1], next[i]] = [next[i], next[i - 1]];
          onChange(next);
        }}>↑ Move up</button><button type="button" disabled={i === value.length - 1} aria-label={`Move item ${i + 1} down`} onClick={() => {
          const next = [...value];
          [next[i + 1], next[i]] = [next[i], next[i + 1]];
          onChange(next);
        }}>↓ Move down</button><button type="button" onClick={() => {
          if (window.confirm('Remove this item from the draft? The live site will not change until you publish.')) onChange(value.filter((_, index) => index !== i));
        }}>Remove</button></div><Fields uploadLimit={uploadLimit} value={item} sample={(sample as unknown[])[0]} path={`${path}-${i}`} onMessage={onMessage} onChange={v => onChange(value.map((old, index) => index === i ? v : old))} /></fieldset>)}<button type="button" className={styles.add} disabled={value.length >= 40} onClick={() => onChange([...value, emptyLike((sample as unknown[])[0])])}>+ Add item</button></div>;
  if (typeof value === 'object' && value) return <div className={styles.fields}>{Object.entries(value).map(([key, v]) => <div className={styles.field} key={key}>{typeof v === 'string' ? <><label htmlFor={`${path}-${key}`}>{labels[key] || key}</label>{['introduction', 'about', 'summary', 'text', 'description', 'contactText'].includes(key) ? <textarea id={`${path}-${key}`} rows={4} value={v} maxLength={12000} onChange={e => onChange({
          ...value,
          [key]: e.target.value
        })} /> : <input id={`${path}-${key}`} value={v} maxLength={12000} onChange={e => onChange({
          ...value,
          [key]: e.target.value
        })} />} {fileFields.has(key) && <label className={styles.upload}>{uploading ? 'Uploading…' : `Upload ${key === 'cv' ? 'PDF' : 'image'} (max ${uploadLimit / 1024 / 1024} MB)`}<input type="file" disabled={uploading} accept={key === 'cv' ? 'application/pdf' : 'image/png,image/jpeg,image/webp'} onChange={async e => {
            const file = e.target.files?.[0];
            if (!file) return;
            if (file.size > uploadLimit) {
              onMessage(`Choose a file no larger than ${uploadLimit / 1024 / 1024} MB.`);
              return;
            }
            setUploading(true);
            try {
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
                ...(latestValue.current as object),
                [key]: result.url
              });
              onMessage('Uploaded. Save the draft, then publish when ready.');
            } catch (error) {
              onMessage(error instanceof Error ? error.message : 'Upload failed');
            } finally {
              setUploading(false);
              e.target.value = '';
            }
          }} /></label>}{key === 'slug' && <small>Changing a published address can break existing links. Keep it stable.</small>}</> : <><h3>{labels[key] || key}</h3><Fields uploadLimit={uploadLimit} value={v} sample={(sample as Record<string, unknown>)[key]} path={`${path}-${key}`} onMessage={onMessage} onChange={next => onChange({
          ...value,
          [key]: next
        })} /></>}</div>)}</div>;
  return null;
}
async function api(path: string, body?: unknown) {
  const response = await fetch(`/api/cms/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : {
      'Content-Type': 'application/json'
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store'
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
export default function Dashboard() {
  const [uploadLimit, setUploadLimit] = useState(1024 * 1024);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [content, setContent] = useState<Content>(initialContent);
  const [active, setActive] = useState<keyof Content>('profile');
  const [key, setKey] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [versions, setVersions] = useState<{
    id: number;
    created_at: string;
  }[]>([]);
  const frame = useRef<HTMLIFrameElement>(null);
  const [previewWidth, setPreviewWidth] = useState('390');
  const [showPreview, setShowPreview] = useState(false);
  useEffect(() => {
    const send = () => frame.current?.contentWindow?.postMessage({
      type: 'portfolio-preview',
      content
    }, window.location.origin);
    send();
    const receive = (event: MessageEvent) => {
      if (event.origin === window.location.origin && event.source === frame.current?.contentWindow && event.data?.type === 'portfolio-preview-ready') send();
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [content, showPreview]);
  const dirty = !!snapshot && JSON.stringify(content) !== JSON.stringify(snapshot.draft);
  async function refresh() {
    const data = await api('content');
    setSnapshot(data);
    setUploadLimit(data.uploadLimit ?? 1024 * 1024);
    setContent(data.draft);
    setVersions(await api('versions'));
  }
  useEffect(() => {
    let alive = true;
    Promise.all([api('content'), api('versions')]).then(([data, history]) => {
      if (alive) {
        setSnapshot(data);
        setUploadLimit(data.uploadLimit ?? 1024 * 1024);
        setContent(data.draft);
        setVersions(history);
      }
    }).catch(error => {
      if (alive && error.message !== 'Sign in to continue') setMessage(error.message);
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage('');
    try {
      await action();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }
  async function login(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      await api('login', {
        key
      });
      setKey('');
      await refresh();
    });
  }
  if (loading) return <main className={styles.dashboard}><p role="status">Opening your dashboard…</p></main>;
  if (!snapshot) return <main className={styles.login}><a href="/">← Portfolio</a><div><p className={styles.kicker}>ELIJAH PETERS / CONTENT STUDIO</p><h1>Your work.<br />Your words.</h1><p>Sign in to manage your portfolio. Your access key stays out of the published site.</p><form onSubmit={login}><label htmlFor="access-key">Admin access key</label><input id="access-key" type="password" value={key} autoComplete="current-password" required maxLength={256} onChange={e => setKey(e.target.value)} /><button disabled={busy}>{busy ? 'Signing in…' : 'Sign in →'}</button></form><p role="status">{message}</p><small>First-time setup is documented in the repository README.</small></div></main>;
  const section = sections.find(s => s.key === active)!;
  return <main className={styles.dashboard}><header className={styles.header}><div><a href="/">Elijah Peters<span>.</span></a><p>CONTENT STUDIO</p></div><div><a href="/" target="_blank" rel="noreferrer">View site ↗</a><button disabled={busy} onClick={() => run(async () => {
          if (dirty && !window.confirm('Discard unsaved edits and sign out?')) return;
          await api('logout', {});
          setSnapshot(null);
        })}>Sign out</button></div></header><div className={styles.toolbar}><div><strong>{dirty ? 'Unsaved edits' : 'Draft saved'}</strong><p>{snapshot.publishedAt ? `Last published ${new Date(snapshot.publishedAt).toLocaleString()}` : 'Initial content · not yet published from dashboard'}</p></div><div><button disabled={busy || !dirty && snapshot.revision !== 0} onClick={() => run(async () => {
          validateContent(content);
          const result = await api('content', {
            content,
            revision: snapshot.revision
          });
          setSnapshot({
            ...snapshot,
            draft: content,
            revision: result.revision
          });
          setMessage('Draft saved. Your live site has not changed.');
        })}>Save draft</button><a href="/admin/preview" target="_blank" rel="noreferrer" onClick={e => {
          if (dirty) {
            e.preventDefault();
            setMessage('Save your draft before previewing.');
          }
        }}>Preview ↗</a><button className={styles.primary} disabled={busy || dirty || snapshot.revision === 0} onClick={() => run(async () => {
          if (!window.confirm('Publish the saved draft? These changes will be visible on the public portfolio.')) return;
          await api('publish', {
            revision: snapshot.revision
          });
          await refresh();
          setMessage('Published. Content is live without a code deployment.');
        })}>{busy ? 'Working…' : 'Publish changes'}</button></div></div><p className={styles.notice} role="status" aria-live="polite">{message || 'Edit → save draft → preview → publish. Content changes do not require a deployment.'}</p><div className={styles.layout}><aside><nav aria-label="Content sections">{sections.map(s => <button key={s.key} aria-current={active === s.key ? 'page' : undefined} onClick={() => setActive(s.key)}>{s.label} <span aria-hidden="true">→</span></button>)}</nav><details><summary>Backups & history</summary><button onClick={() => {
            const blob = new Blob([JSON.stringify(content, null, 2)], {
              type: 'application/json'
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'portfolio-content.json';
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }}>Export current content</button><label className={styles.upload}>Import content backup<input type="file" accept="application/json,.json" onChange={async e => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                if (file.size > 512 * 1024) throw new Error('Backup is too large');
                const imported = validateContent(JSON.parse(await file.text()));
                if (window.confirm('Replace the draft editor with this backup? Nothing is published yet.')) {
                  setContent(imported);
                  setMessage('Backup loaded into the editor. Save and preview before publishing.');
                }
              } catch (error) {
                setMessage(error instanceof Error ? error.message : 'Invalid backup');
              } finally {
                e.target.value = '';
              }
            }} /></label><p>Restore creates a draft. It does not change the live site.</p>{versions.map(v => <button key={v.id} disabled={busy} onClick={() => run(async () => {
            if (!window.confirm(`Restore version ${v.id} to the draft? Unsaved edits will be replaced.`)) return;
            await api('restore', {
              id: v.id,
              revision: snapshot.revision
            });
            await refresh();
            setMessage('Earlier version restored to draft. Preview before publishing.');
          })}>Version {v.id}<small>{new Date(v.created_at).toLocaleString()}</small></button>)}</details></aside><section className={styles.editor}><p className={styles.kicker}>PORTFOLIO CONTENT</p><h1>{section.label}</h1><p>{section.description}</p><button type="button" onClick={() => setShowPreview(!showPreview)}>{showPreview ? 'Hide live preview' : 'Open live design preview'}</button>{showPreview && <div className={styles.previewPanel}><label>Preview width<select value={previewWidth} onChange={e => setPreviewWidth(e.target.value)}><option value="390">Mobile · 390px</option><option value="1100">Desktop · 1100px</option></select></label><p>Unsaved edits appear here when valid. Nothing is published.</p><div className={styles.previewScroll}><iframe ref={frame} title="Live portfolio design preview" src="/admin/canvas" style={{
              width: Number(previewWidth),
              height: 760
            }} /></div></div>}<fieldset disabled={busy} className={styles.editorFields}>{active === 'design' ? <Designer onMessage={setMessage} value={content.design} onChange={design => setContent(current => ({
            ...current,
            design
          }))} /> : <Fields uploadLimit={uploadLimit} value={content[active]} sample={initialContent[active]} path={active} onMessage={setMessage} onChange={value => setContent(current => ({
            ...current,
            [active]: value
          }))} />}</fieldset></section></div></main>;
}
