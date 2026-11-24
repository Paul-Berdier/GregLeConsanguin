'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { livePosition } from '@/lib/playerUtils';
import { EASE, reducedMotion } from '@/lib/motion';
import { clockText, endsAt, fmtLong, queueSeconds } from '@/lib/queue/view';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import QueuePanel from '@/components/Queue/QueuePanel';
import HistoryPanel from '@/components/History/HistoryPanel';
import Suggestions from '@/components/History/Suggestions';
import LibraryPanel from '@/components/Library/LibraryPanel';
import { librarySummary } from '@/components/Library/meta';
import { useLibrary, useLibraryInit } from '@/hooks/useLibrary';

type Tab = 'queue' | 'hist' | 'lib';
/** Ordre des onglets : ← → les parcourent en boucle, Début et Fin vont au premier et au dernier. */
const TABS: readonly Tab[] = ['queue', 'hist', 'lib'];
/** Place libre sous la file au-delà de laquelle les ménestrels du Codex Manesse tiennent compagnie (DESIGN §12.5). */
const ROOMY_PX = 190;

/**
 * Le panneau de droite (DESIGN §3, §12.5 ; body.html, lignes 159–209) : titre en Grenze Gotisch, résumé de la
 * file (« File d'attente · 8 titres · 47 min · fin vers 22 h 47 »), onglets à pilule glissante, trois volets
 * toujours montés (défilement gardé) qui se relaient : sortie 60 ms, entrée 140 ms (motion.md §6.14).
 * Troisième volet : le chansonnier du Roi (Library/, spec 2026-11-23 §3), lu à la connexion (useLibraryInit).
 * Styles : panel.css.
 */
export default function Sidebar({ booted = true }: { booted?: boolean }) {
  useLibraryInit();
  const [tab, setTab] = useState<Tab>('queue');
  const [roomy, setRoomy] = useState(false);
  const [, setMinute] = useState(0);
  const queue = useStore((s) => s.player.queue);
  const hasCurrent = useStore((s) => !!s.player.current);
  const paused = useStore((s) => s.player.paused);
  const tickBase = useStore((s) => s.tickBase);
  const lib = useLibrary((s) => s.lib);
  const libStatus = useLibrary((s) => s.status);
  const panelRef = useRef<HTMLElement>(null);
  const incoming = useRef<Tab | null>(null);
  /** L'onglet visé pendant le fondu de sortie (60 ms) : le dernier choix, clic ou flèche, l'emporte. */
  const target = useRef<Tab | null>(null);
  const anims = useRef<Animation[]>([]);

  useEffect(() => {
    const id = setInterval(() => setMinute((m) => m + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const n = queue.length;
  const remaining = hasCurrent ? Math.max(0, tickBase.dur - livePosition(tickBase, paused, performance.now())) : 0;
  const summary = !booted ? t('queue.tab.zero') : !n ? t('queue.empty.title')
    : `${t('queue.subtitle', { n })}${t('queue.durationSuffix', { dur: fmtLong(queueSeconds(queue)) })} · ${tx('queue.endsAt', { time: clockText(endsAt(Date.now(), remaining, queue)) })}`;
  const libSummary = lib ? librarySummary(lib) : libStatus === 'error' ? tx('library.failed') : libStatus === 'loading' ? tx('library.loading') : '';

  const groupOf = (x: Tab) => Array.from(panelRef.current?.querySelectorAll<HTMLElement>(`[data-pane="${x}"]`) ?? []);

  // l'ancien volet s'efface (60 ms), puis le nouveau entre (140 ms, 4 px) : jamais deux listes à la fois
  const switchTo = (next: Tab) => {
    if (next === (target.current ?? tab)) return;
    for (const a of anims.current) a.cancel();
    anims.current = [];
    // retour à l'onglet affiché pendant son fondu : l'annulation le rend, setTab efface un changement en attente
    if (next === tab) { target.current = null; incoming.current = null; setTab(next); return; }
    target.current = next;
    if (reducedMotion()) { setTab(next); return; }
    const outs = groupOf(tab).map((el) => el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 60, easing: 'ease-out', fill: 'forwards' }));
    anims.current = outs;
    (outs[0]?.finished ?? Promise.resolve()).then(() => { incoming.current = next; setTab(next); }, () => {});
  };
  useLayoutEffect(() => {
    target.current = null;
    for (const a of anims.current) a.cancel();
    anims.current = [];
    if (incoming.current !== tab) return;
    incoming.current = null;
    anims.current = groupOf(tab).map((el) => el.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }],
      { duration: 140, easing: EASE.out, fill: 'backwards' }));
  }, [tab]);

  // les ménestrels : seulement quand la file laisse assez de place vide (contenu : .qcontent, QueuePanel.tsx)
  useLayoutEffect(() => {
    const sc = panelRef.current?.querySelector<HTMLElement>('[data-pane="queue"] .scroller');
    const content = sc?.querySelector<HTMLElement>('.qcontent');
    if (!sc || !content) return;
    const measure = () => setRoomy(tab === 'queue' && sc.clientHeight - content.offsetHeight > ROOMY_PX);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(sc);
    ro.observe(content);
    return () => ro.disconnect();
  }, [tab]);

  // ← → : l'onglet voisin, en boucle, depuis l'onglet visé (pendant un fondu, le dernier choix) ; Début, Fin : les bouts
  const onTabsKey = (e: KeyboardEvent) => {
    const at = TABS.indexOf(target.current ?? tab);
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? TABS.length - 1 : 0;
    const next = e.key === 'Home' ? TABS[0] : e.key === 'End' ? TABS[TABS.length - 1] : step ? TABS[(at + step) % TABS.length] : null;
    if (!next) return;
    e.preventDefault();
    switchTo(next);
    panelRef.current?.querySelector<HTMLElement>(`#tab-${next}`)?.focus();
  };

  return (
    <aside className="panel" ref={panelRef} aria-label={tx('library.panelLabel')} data-roomy={roomy}>
      <img className="minstrels" src="/gothique/minstrels-manesse-line.webp" alt="" aria-hidden="true" width={480} height={355} decoding="async"/>
      <div className="panel-head">
        <div className="ptitle-slot">
          <h2 className="ptitle" data-pane="queue" aria-hidden={tab !== 'queue'}>{t('queue.title')}</h2>
          <h2 className="ptitle" data-pane="hist" aria-hidden={tab !== 'hist'}>{t('history.title')}</h2>
          <h2 className="ptitle" data-pane="lib" aria-hidden={tab !== 'lib'}>{tx('library.title')}</h2>
        </div>
        <div className="tabs" role="tablist" aria-label={tx('panel.tabs')} data-tab={tab} onKeyDown={onTabsKey}>
          <span className="pill" aria-hidden="true"/>
          <button type="button" role="tab" id="tab-queue" aria-selected={tab === 'queue'} aria-controls="pane-queue"
            tabIndex={tab === 'queue' ? 0 : -1} className="tab" onClick={() => switchTo('queue')}>
            {tx('panel.queueTab')} <span className="count tnum">{booted ? n : '—'}</span>
          </button>
          <button type="button" role="tab" id="tab-hist" aria-selected={tab === 'hist'} aria-controls="pane-hist"
            tabIndex={tab === 'hist' ? 0 : -1} className="tab" onClick={() => switchTo('hist')}>
            {t('history.tab')}
          </button>
          <button type="button" role="tab" id="tab-lib" aria-selected={tab === 'lib'} aria-controls="pane-lib"
            tabIndex={tab === 'lib' ? 0 : -1} className="tab" onClick={() => switchTo('lib')}>
            {tx('library.tab')}
          </button>
        </div>
        {/* le résumé, sous le titre : toute la largeur du panneau (les onglets ont leur propre rangée) */}
        <div className="ptitle-slot psubs">
          <div className="psub tnum" data-pane="queue" aria-hidden={tab !== 'queue'}>{summary}</div>
          <div className="psub" data-pane="hist" aria-hidden={tab !== 'hist'}>{t('history.subtitle')}</div>
          <div className="psub tnum" data-pane="lib" aria-hidden={tab !== 'lib'}>{libSummary}</div>
        </div>
      </div>
      <div className="panes">
        <div className="pane" id="pane-queue" role="tabpanel" aria-labelledby="tab-queue" data-pane="queue" aria-hidden={tab !== 'queue'}>
          <QueuePanel after={<Suggestions/>}/>
        </div>
        <div className="pane" id="pane-hist" role="tabpanel" aria-labelledby="tab-hist" data-pane="hist" aria-hidden={tab !== 'hist'}>
          <HistoryPanel/>
        </div>
        <div className="pane" id="pane-lib" role="tabpanel" aria-labelledby="tab-lib" data-pane="lib" aria-hidden={tab !== 'lib'}>
          <LibraryPanel/>
        </div>
      </div>
    </aside>
  );
}
