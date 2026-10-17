import type { CSSProperties } from 'react';
import type { Design } from './content';
export function themeStyle(d: Design): CSSProperties {
  const fonts = {
    modern: 'Arial, Helvetica, sans-serif',
    editorial: 'Georgia, Times New Roman, serif',
    technical: 'ui-monospace, SFMono-Regular, Consolas, monospace'
  };
  return {
    '--paper': d.colors.paper,
    '--ink': d.colors.ink,
    '--muted': d.colors.muted,
    '--surface': d.colors.surface,
    '--line': d.colors.line,
    '--accent': d.colors.accent,
    '--button-text': d.colors.buttonText,
    '--section-space': `${d.spacing}px`,
    '--radius': `${d.radius}px`,
    '--content-width': `${d.width}px`,
    '--font': fonts[d.typography as keyof typeof fonts]
  } as CSSProperties;
}
