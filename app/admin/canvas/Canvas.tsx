'use client';

import { useEffect, useState } from 'react';
import { validateContent, type Content } from '../../cms/content';
import Portfolio from '../../cms/Portfolio';
export default function Canvas({
  initial
}: {
  initial: Content;
}) {
  const [content, setContent] = useState(initial);
  const [error, setError] = useState('');
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== window.parent || event.data?.type !== 'portfolio-preview') return;
      try {
        setContent(validateContent(event.data.content));
        setError('');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Complete the fields to preview.');
      }
    };
    window.addEventListener('message', receive);
    window.parent.postMessage({
      type: 'portfolio-preview-ready'
    }, window.location.origin);
    return () => window.removeEventListener('message', receive);
  }, []);
  return <>{error && <div role="status" style={{
      padding: 16,
      background: '#ffedb8',
      color: '#30260d'
    }}>Showing the last valid design. {error}</div>}<Portfolio content={content} preview /></>;
}
