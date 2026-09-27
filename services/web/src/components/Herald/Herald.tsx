'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { spokenText, stackHeight, stackLayout } from '@/lib/herald';
import { tx } from '@/theme/copy.extra';
import { herald, setAnnouncer, useToasts } from './store';

const ICON = {
  ok: <path d="M5 12.5l4.5 4.5L19 7.5"/>,
  warn: <path d="M12 6v8M12 18v.5"/>,
  err: <path d="M7 7l10 10M17 7L7 17"/>,
  info: <path d="M12 10.5v8M12 6v.5"/>,
};

// Ctrl+Z (Cmd+Z) ailleurs que dans un champ : la dernière annulation proposée
function isTextField(el: EventTarget | null): boolean {
  const n = el as HTMLElement | null;
  const tag = n?.tagName?.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || !!n?.isContentEditable;
}

/**
 * Le Héraut (DESIGN §5 et §12.6) : plaques plombées empilées au-dessus du pied du panneau (au centre en bas
 * quand le panneau n'est pas là : déconnecté, une colonne). Survol ou focus : la pile se déplie et attend.
 * Échap renvoie la notification qui a le focus. Les faits sont lus par deux régions aria-live persistantes
 * (polie, ou assertive pour une erreur) ; la réplique de Greg, en or, reste hors de l'annonce. Styles : herald.css.
 */
export default function Herald({ dock }: { dock: 'panel' | 'center' }) {
  const toasts = useToasts();
  const refs = useRef(new Map<number, HTMLDivElement>());
  const politeRef = useRef<HTMLDivElement>(null);
  const alertRef = useRef<HTMLDivElement>(null);
  const roomRef = useRef('');
  const sectionRef = useRef<HTMLElement>(null);
  const layoutRef = useRef<() => void>(() => {});
  const roRef = useRef<ResizeObserver | null>(null);
  const observed = useRef(new Set<Element>());
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const shown = toasts.filter((x) => !x.leaving);
  const active = (hover || focus) && shown.length > 0;

  useEffect(() => {
    setAnnouncer((x) => {
      const el = x.kind === 'err' ? alertRef.current : politeRef.current;
      if (!el) return;
      const text = spokenText(x, (label) => tx('herald.undoHint', { label }));
      el.textContent = '';
      setTimeout(() => { el.textContent = text; }, 40);
    });
    return () => setAnnouncer(null);
  }, []);

  // Une plaque retirée sous le pointeur ou avec le focus (« Annuler » cliqué) ne déclenche ni mouseleave ni
  // blur : on revérifie à chaque changement de la pile, sinon les minuteurs resteraient arrêtés.
  useEffect(() => {
    const sec = sectionRef.current;
    if (!sec) return;
    if (focus && !sec.contains(document.activeElement)) setFocus(false);
    if (hover && !sec.matches(':hover')) setHover(false);
  }, [toasts, focus, hover]);

  // survol ou focus : les minuteurs attendent, la pile se déplie
  useEffect(() => {
    if (!active) return;
    herald.hold();
    return () => herald.release();
  }, [active]);

  // onglet caché (dès le montage s'il l'est déjà) : les minuteurs attendent, puis reprennent où ils en étaient
  useEffect(() => {
    let held = false;
    const on = () => {
      if (document.hidden && !held) { held = true; herald.hold('tab'); }
      else if (!document.hidden && held) { held = false; herald.release('tab'); }
    };
    on();
    document.addEventListener('visibilitychange', on);
    return () => { document.removeEventListener('visibilitychange', on); if (held) herald.release('tab'); };
  }, []);

  useEffect(() => {
    const on = (e: globalThis.KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== 'z' || isTextField(e.target)) return;
      if (herald.undo()) e.preventDefault();
    };
    document.addEventListener('keydown', on);
    return () => document.removeEventListener('keydown', on);
  }, []);

  // Un texte qui se replie autrement (police chargée en retard, panneau élargi ou rétréci) change la hauteur
  // d'une plaque sans rendu React : on observe le corps de chaque plaque et on refait la pile.
  useLayoutEffect(() => {
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => layoutRef.current());
    const seen = observed.current;
    roRef.current = ro;
    return () => { ro.disconnect(); roRef.current = null; seen.clear(); };
  }, []);

  // Place de chaque plaque (variables --y --s --o, hauteur de la pile repliée, plaques cachées inertes) ;
  // la file garde la hauteur de la pile repliée (--herald-h). Les plaques qui sortent gardent leur dernière place.
  useLayoutEffect(() => {
    layoutRef.current = () => {
      const els = shown.map((x) => refs.current.get(x.id) ?? null);
      // hauteurs réelles : la hauteur imposée d'une plaque repliée est levée le temps de la mesure (avant l'affichage)
      for (const el of els) if (el) el.style.height = '';
      const heights = els.map((el) => el?.offsetHeight ?? 0);
      const pos = stackLayout(heights, active);
      els.forEach((el, i) => {
        if (!el) return;
        const p = pos[i];
        el.style.setProperty('--y', `${p.y}px`);
        el.style.setProperty('--s', String(p.s));
        el.style.setProperty('--o', String(p.o));
        el.style.zIndex = String(p.z);
        el.style.height = p.fold == null ? '' : `${p.fold}px`;
        el.toggleAttribute('data-folded', p.fold != null);
        el.toggleAttribute('data-hidden', p.hidden);
        el.inert = p.hidden;
      });
      const h = stackHeight(heights);
      const room = h ? `${h + 16}px` : '0px';
      if (room !== roomRef.current) { roomRef.current = room; document.documentElement.style.setProperty('--herald-h', room); }
      const ro = roRef.current;
      if (!ro) return;
      const bodies = new Set<Element>();
      for (const el of els) { const b = el?.querySelector('.body'); if (b) bodies.add(b); }
      for (const b of observed.current) if (!bodies.has(b)) { ro.unobserve(b); observed.current.delete(b); }
      for (const b of bodies) if (!observed.current.has(b)) { ro.observe(b); observed.current.add(b); }
    };
    layoutRef.current();
  });

  // Échap : la notification qui a le focus s'en va ; le focus passe à l'« Annuler » d'une autre, s'il y en a une.
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== 'Escape') return;
    const cur = (e.target as HTMLElement).closest<HTMLElement>('.toast');
    const id = Number(cur?.dataset.id);
    if (!cur || !id) return;
    e.preventDefault();
    const next = [...e.currentTarget.querySelectorAll<HTMLElement>('.toast:not([data-leaving]):not([data-hidden]) .undo')]
      .find((b) => !cur.contains(b));
    herald.dismiss(id);
    if (next) next.focus();
    else (e.target as HTMLElement).blur();
  };

  return (
    <>
      <section className="toasts" ref={sectionRef} data-dock={dock} aria-label={tx('herald.region')}
        onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
        onFocus={() => setFocus(true)}
        onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocus(false); }}
        onKeyDown={onKeyDown}>
        {toasts.map((x) => (
          <div key={x.id} className="toast plaque" data-id={x.id} data-kind={x.kind} data-leaving={x.leaving || undefined}
            ref={(el) => { if (el) refs.current.set(x.id, el); else refs.current.delete(x.id); }}
            onClick={(e) => { if (!(e.target as HTMLElement).closest('.undo')) herald.dismiss(x.id); }}>
            <span className="ic" aria-hidden="true">
              {x.quip && <img className="greg" src="/gothique/greg-face-96.webp" alt="" width={22} height={22} decoding="async"/>}
              <svg className="ico" viewBox="0 0 24 24">{ICON[x.kind]}</svg>
            </span>
            <div className="body">
              <div className="fact">{x.fact}{x.n > 1 && <span className="x tnum">×{x.n}</span>}</div>
              {x.quip && <div className="qp" aria-hidden="true">{x.quip}</div>}
            </div>
            {x.action && <button type="button" className="undo" onClick={() => herald.act(x.id)}>{x.action.label}</button>}
          </div>
        ))}
      </section>
      <div className="sr" aria-live="polite" ref={politeRef}/>
      <div className="sr" aria-live="assertive" ref={alertRef}/>
    </>
  );
}
