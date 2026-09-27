'use client';

import { EASE, SPRING, reducedMotion } from '@/lib/motion';
import { SEAL_FLIGHT_MS, SEAL_STAMP_DELAY_MS } from '@/lib/queue/seal';
import type { SealExpect } from '@/lib/queue/seal';
import { boxOf } from '@/lib/stage/coronation';
import type { Box } from '@/lib/stage/coronation';

/**
 * Le Sceau (DESIGN §5, motion.md §6.5) : la ligne entre avec le seul rebond de l'app, le sceau du Roi se pose,
 * la pochette source vole jusqu'à elle. Mouvement réduit : fondu de 150 ms, ni vol ni défilement doux (la ligne est
 * quand même amenée en vue, comme scrollIntoList du prototype). data-sealed : pour la vérification.
 */
export function stampRow(li: HTMLElement, w: SealExpect): void {
  li.dataset.sealed = '';
  const reduce = reducedMotion();
  if (reduce) li.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 150, easing: 'ease', fill: 'backwards' });
  else {
    const spring: KeyframeAnimationOptions = { duration: SPRING.seal.dur, easing: SPRING.seal.easing, fill: 'backwards' };
    li.animate([{ opacity: 0, transform: 'scale(.9)' }, { opacity: 1, transform: 'none' }], spring);
    li.querySelector<HTMLElement>('.thumb .seal')?.animate(
      [{ opacity: 0, transform: 'scale(1.35) rotate(-14deg)' }, { opacity: 1, transform: 'none' }], { ...spring, delay: SEAL_STAMP_DELAY_MS });
  }
  const sc = li.closest<HTMLElement>('.scroller');
  const r = li.getBoundingClientRect(), c = sc?.getBoundingClientRect();
  if (sc && c && (r.bottom > c.bottom - 20 || r.top < c.top)) sc.scrollTo({ top: li.offsetTop - 40, behavior: reduce ? 'auto' : 'smooth' });
  if (!reduce && w.from && w.thumb) fly(w.from, w.thumb, li);
}

/**
 * La pochette source vole jusqu'à la ligne (app.js, lignes 1154–1166 : fly), au cadre suivant, une fois la ligne
 * placée et défilée. File cachée (onglet Annales) : vers le compteur de l'onglet, réduite à 0.4 et effacée.
 * Le fantôme est un `div.seal-ghost` fixe, de la taille de la source, étiré par transform seul (origine 0 0).
 */
function fly(from: Box, thumb: string, li: HTMLElement): void {
  requestAnimationFrame(() => {
    const toCount = document.getElementById('pane-queue')?.getAttribute('aria-hidden') === 'true';
    const target = toCount ? document.querySelector<HTMLElement>('#tab-queue .count') : li.querySelector<HTMLElement>('.thumb > .im');
    if (!target || !li.isConnected || from.width <= 0 || from.height <= 0) return;
    const to = boxOf(target);
    const g = document.createElement('div');
    g.className = 'seal-ghost';
    g.setAttribute('aria-hidden', 'true');
    g.style.width = `${from.width}px`;
    g.style.height = `${from.height}px`;
    g.style.backgroundImage = `url(${JSON.stringify(thumb)})`;
    document.body.appendChild(g);
    if (!toCount) target.style.visibility = 'hidden';
    const sx = toCount ? 0.4 : to.width / from.width, sy = toCount ? 0.4 : to.height / from.height;
    const done = (): void => { g.remove(); if (!toCount) target.style.removeProperty('visibility'); };
    g.animate([
      { transform: `translate(${from.left}px, ${from.top}px) scale(1)`, opacity: 1 },
      { transform: `translate(${to.left}px, ${to.top}px) scale(${sx}, ${sy})`, opacity: toCount ? 0 : 1 },
    ], { duration: SEAL_FLIGHT_MS, easing: EASE.drawer, fill: 'forwards' }).finished.then(done, done);
  });
}
