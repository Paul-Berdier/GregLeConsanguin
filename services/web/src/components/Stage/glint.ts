'use client';

import { DUR, EASE, reducedMotion } from '@/lib/motion';

/**
 * Le reflet d'or (DESIGN §5, app.js `glint()`, lignes 502–514) : une bande de lumière passe une fois sur le titre
 * couronné. La bande glisse d'un côté, le texte doré qu'elle porte de l'autre : le reflet reste posé sur les lettres.
 * translateX seulement ; rien en mouvement réduit. Styles : .glint, now.css. Appelé par NowPlaying.tsx.
 */
export function runGlint(slot: HTMLElement): void {
  if (reducedMotion()) return;
  const line = slot.querySelector<HTMLElement>(':scope > .line:not([aria-hidden])');
  if (!line) return;
  for (const old of slot.querySelectorAll(':scope > .glint')) old.remove();   // un reflet à la fois
  const W = Math.min(slot.clientWidth, line.scrollWidth), B = Math.max(140, W * 0.3);
  const g = document.createElement('div');
  g.className = 'glint';
  g.setAttribute('aria-hidden', 'true');
  const band = document.createElement('div');
  band.className = 'glint-band';
  band.style.width = `${B}px`;
  const text = document.createElement('div');
  text.className = 'glint-text';
  text.textContent = line.textContent;
  text.style.width = `${slot.clientWidth}px`;
  band.appendChild(text);
  g.appendChild(band);
  slot.appendChild(g);
  const o: KeyframeAnimationOptions = { duration: DUR.glint, easing: EASE.inOut, fill: 'both' };
  band.animate([{ transform: `translateX(${-B}px)` }, { transform: `translateX(${W}px)` }], o);
  const done = (): void => { g.remove(); };
  text.animate([{ transform: `translateX(${B}px)` }, { transform: `translateX(${-W}px)` }], o).finished.then(done, done);
}
