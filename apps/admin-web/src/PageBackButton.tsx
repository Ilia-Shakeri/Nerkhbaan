import { useEffect, useRef } from 'react';
export function PageBackButton() {
  const trail = useRef([window.location.hash]);
  useEffect(() => {
    const changed = () => {
      const hash = window.location.hash;
      if (trail.current[trail.current.length - 2] === hash) trail.current.pop();
      else if (trail.current[trail.current.length - 1] !== hash) trail.current.push(hash);
    };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  return <button type="button" className="page-back-button" aria-label="Back" title="بازگشت" onClick={() => {
    if (trail.current.length > 1) window.history.back();
    else window.location.assign('/');
  }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m12 5-7 7 7 7M5 12h14" /></svg></button>;
}
