'use client';

import { useState, useEffect } from 'react';
import { playerActions, usePlayer, usePlayerInit, useStore } from '@/hooks/usePlayer';
import { HELP_EVENT, shortcutFor } from '@/lib/keys';
import type { Shortcut } from '@/lib/keys';
import { watchReducedMotion } from '@/lib/motion';
import { kingOrders, NEXT } from '@/lib/stage/coronation';
import { tx } from '@/theme/copy.extra';
import { speak } from '@/components/Herald/store';
import Herald from '@/components/Herald/Herald';
import Header from '@/components/Header/Header';
import Stage from '@/components/Stage/Stage';
import Sidebar from '@/components/Sidebar';

const FOCUS_REFRESH_MIN_MS = 15000;

// Clavier de la page (DESIGN §7 et §12.7) : cibles lues au moment de la touche
const SEARCH = '.top .field input';
const FIELD = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
const CONTROL = 'button, a[href], [role="button"], [role="switch"], [role="tab"], [role="slider"], [role="option"]';
/** Commandes du lecteur : il leur faut un serveur. « / », « ? » et la saisie directe servent sans (le choix du serveur y guide). */
const PLAYS: readonly Shortcut[] = ['togglePause', 'skip', 'restart'];

/** « Aller à la file » : la ligne active de la file, sinon l'onglet File (volet Historique affiché : la ligne, cachée, refuserait le focus). */
function focusQueue(): void {
  const shown = document.getElementById('pane-queue')?.getAttribute('aria-hidden') !== 'true';
  (shown && document.querySelector<HTMLElement>('.qcontent > .qlist > .row[tabindex="0"]') || document.getElementById('tab-queue'))?.focus();
}

// ═══════════════════════════════
// Main Page
// ═══════════════════════════════
export default function Home() {
  usePlayerInit();
  const { boot, refreshMe, me } = usePlayer();
  const [booted, setBooted] = useState(false);

  useEffect(() => { boot().then(() => setBooted(true)).catch(() => setBooted(true)); }, [boot]);

  // Mouvement réduit suivi en direct (DESIGN §12.6) : <html data-motion> pour les feuilles et les chorégraphies
  useEffect(() => watchReducedMotion((r) => { document.documentElement.dataset.motion = r ? 'reduced' : 'full'; }), []);

  // Un seul gestionnaire de raccourcis (lib/keys) ; l'interrupteur du menu du compte le coupe (WCAG 2.1.4)
  useEffect(() => {
    const handler = (ev: KeyboardEvent) => {
      if (ev.defaultPrevented) return;   // déjà traitée : onglets (Maj+→ y changerait aussi de titre), listes, popovers
      const el = ev.target instanceof Element ? ev.target : null, s = useStore.getState();
      const act = shortcutFor(ev, {
        enabled: document.documentElement.dataset.keys !== 'off', loggedIn: !!s.me,
        inField: !!el?.closest(FIELD), inPopover: !!el?.closest('.pop[data-open="true"]'), onRow: !!el?.closest('.qlist > .row'),
        onControl: !!el?.closest(CONTROL), dragging: document.body.classList.contains('is-dragging'),
      });
      if (!act) return;
      if (!s.guildId && PLAYS.includes(act)) return;   // sans serveur : Espace et Maj+→/← restent au navigateur
      const search = document.querySelector<HTMLInputElement>(SEARCH);
      // Focus pendant keydown, curseur en fin : la lettre s'ajoute au texte du champ (prototype : value += key),
      // au lieu de tomber à l'ancien curseur ou de remplacer une sélection restée là
      if (act === 'type') {
        if (search) { search.focus(); const n = search.value.length; search.setSelectionRange(n, n); }
        return;
      }
      ev.preventDefault();
      // Les erreurs passent par le Héraut (usePlayer) ; pause et suivant sont optimistes
      if (act === 'search') search?.focus();
      else if (act === 'help') document.dispatchEvent(new Event(HELP_EVENT));
      else if (act === 'togglePause') {
        if (!s.player.current) return;
        void playerActions.togglePause();
        speak(tx(s.player.paused ? 'a11y.resumed' : 'a11y.paused'));
      } else if (act === 'skip') { kingOrders.mark(NEXT, 'key', performance.now()); void playerActions.skip(); }
      else void playerActions.restartTrack();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Retour sur l'onglet : on revérifie la session, au plus une fois toutes les 15 s et jamais en parallèle
  useEffect(() => {
    let last = 0, inFlight = false;
    const h = () => {
      const now = Date.now();
      if (inFlight || now - last < FOCUS_REFRESH_MIN_MS) return;
      last = now; inFlight = true;
      refreshMe().catch(() => {}).finally(() => { inFlight = false; });
    };
    window.addEventListener('focus', h);
    return () => window.removeEventListener('focus', h);
  }, [refreshMe]);

  return (
    <div className="page-shell">

      {/* Lien d'évitement (DESIGN §7) : premier arrêt de Tab, visible au focus seulement */}
      {booted && me && <a className="skip-link" href="#pane-queue" onClick={(e) => { e.preventDefault(); focusQueue(); }}>{tx('a11y.skipToQueue')}</a>}

      {/* ═══ Header ═══ (marges latérales : --page-x, header.css) */}
      <Header ready={booted}/>

      <div className="flex-1 min-h-0 flex flex-col" style={{
        padding: '0 calc(var(--page-x) + env(safe-area-inset-right, 0px)) calc(8px + env(safe-area-inset-bottom, 0px)) calc(var(--page-x) + env(safe-area-inset-left, 0px))',
        gap: '12px',
      }}>

        {/* ═══ Main ═══ */}
        {/* Scène seule une fois la déconnexion constatée ; pendant le chargement, la grille garde son panneau (pas de saut) */}
        <main className="flex-1 min-h-0 main-layout" data-scene={booted && !me ? 'out' : 'in'}>
          {/* Gauche : la scène (rosace, portail, horloge, transport) */}
          <Stage booted={booted}/>

          {/* Droite : file et historique (étape 3) */}
          <Sidebar booted={booted}/>
        </main>
      </div>

      {/* Le Héraut : au-dessus du pied du panneau ; au centre en bas quand le panneau n'est pas là */}
      <Herald dock={booted && me ? 'panel' : 'center'}/>
    </div>
  );
}
