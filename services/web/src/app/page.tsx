'use client';

import { useState, useEffect } from 'react';
import { playerActions, usePlayer, usePlayerInit, useStore } from '@/hooks/usePlayer';
import { isShortcutIgnored } from '@/lib/playerUtils';
import Herald from '@/components/Herald/Herald';
import Header from '@/components/Header/Header';
import Stage from '@/components/Stage/Stage';
import Sidebar from '@/components/Sidebar';

const FOCUS_REFRESH_MIN_MS = 15000;

// ═══════════════════════════════
// Main Page
// ═══════════════════════════════
export default function Home() {
  usePlayerInit();
  const { boot, refreshMe, me } = usePlayer();
  const [booted, setBooted] = useState(false);

  useEffect(() => { boot().then(() => setBooted(true)).catch(() => setBooted(true)); }, [boot]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (ev: KeyboardEvent) => {
      // Ctrl+R / Cmd+P… restent aux raccourcis du navigateur ; rien dans les champs / select / boutons (Espace)
      if (isShortcutIgnored(ev)) return;
      const s = useStore.getState();
      if (!s.me || !s.guildId) return;
      // Les erreurs passent par le Héraut (usePlayer) ; pause et suivant sont optimistes
      if (ev.code === 'Space') { ev.preventDefault(); void playerActions.togglePause(); }
      else if (ev.key === 'n') void playerActions.skip();
      else if (ev.key === 'p') void playerActions.restartTrack();
      else if (ev.key === 'r') void playerActions.toggleRepeat();
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
