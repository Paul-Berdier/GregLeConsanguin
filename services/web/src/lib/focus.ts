/**
 * Où rendre le focus (DESIGN §12.7, WCAG 2.4.3) : calculs de hooks/useRoving.ts et de Herald/Herald.tsx.
 * Pur, sans import runtime (tests/focus-a11y.test.mjs).
 */

/** Focus perdu sur une liste : la même ligne si elle est encore là (déplacée, remontée), sinon celle qui a pris sa
 * place (`index`, borné à la dernière), sinon null (liste vide). */
export function rescueKey(keys: readonly string[], lost: string, index: number): string | null {
  if (keys.includes(lost)) return lost;
  return keys.length ? keys[Math.min(Math.max(index, 0), keys.length - 1)] : null;
}

/** Focus venu du clavier (:focus-visible) : seul celui-là est rendu à une ligne. Au pointeur (Chrome focalise le bouton
 * cliqué), le rendre garderait les boutons d'une voisine affichés et arrêterait les raccourcis de la page sur une ligne.
 * Navigateur sans :focus-visible : rendu, comme avant. */
export function keyboardFocus(el: Pick<Element, 'matches'>): boolean {
  try { return el.matches(':focus-visible'); } catch { return true; }
}

/**
 * focusout dans une liste : le focus l'a-t-il quittée (ailleurs, ou sur <body> d'un clic) ? Alors `forget`. Décidé après
 * coup (`defer`, une microtâche) : Chrome lance focusout pendant que React retire ou déplace la ligne focalisée, encore
 * dans la liste, activeElement sur <body>. D'ici là, l'effet de rendu a rendu le focus (ligne retirée : plus connectée)
 * ou React l'a remis (ligne déplacée : focus revenu dans la liste). Vers une autre ligne, ou fenêtre quittée
 * (activeElement inchangé) : rien à décider.
 */
export function focusOutWatcher(o: {
  list: () => Node | null;
  active: () => Element | null;
  defer: (fn: () => void) => void;
  forget: () => void;
}): (e: { target: EventTarget | null; relatedTarget: EventTarget | null }) => void {
  return (e) => {
    const list = o.list(), from = e.target as Node | null, to = e.relatedTarget as Node | null;
    if (!list || !from || !list.contains(from) || (to && list.contains(to)) || o.active() === from) return;
    o.defer(() => {
      if (!from.isConnected || o.list()?.contains(o.active())) return;
      o.forget();
    });
  };
}

/** Défilement (px, signé) qui ramène la ligne [top, bottom] dans la vue [viewTop, viewBottom] au plus près ; son haut
 * d'abord quand elle est plus haute que la vue. 0 : déjà visible. */
export function revealDelta(top: number, bottom: number, viewTop: number, viewBottom: number): number {
  if (top < viewTop) return top - viewTop;
  if (bottom > viewBottom) return Math.min(bottom - viewBottom, top - viewTop);
  return 0;
}

/** Plaque `cur` qui s'en va (« Annuler », Échap) : l'« Annuler » d'une autre plaque visible, sinon la ligne active de la
 * file (volet affiché, comme « Aller à la file »), sinon l'onglet File ; null : pas de panneau. */
export function focusAfterToast(section: ParentNode, cur: Element, doc: Document): HTMLElement | null {
  const other = Array.from(section.querySelectorAll<HTMLElement>('.toast:not([data-leaving]):not([data-hidden]) .undo'))
    .find((b) => !cur.contains(b));
  if (other) return other;
  const shown = doc.getElementById('pane-queue')?.getAttribute('aria-hidden') !== 'true';
  return (shown ? doc.querySelector<HTMLElement>('.qcontent > .qlist > .row[tabindex="0"]') : null) ?? doc.getElementById('tab-queue');
}
