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

type Tab = 'queue' | 'hist';
/** Place libre sous la file au-delà de laquelle les ménestrels du Codex Manesse tiennent compagnie (DESIGN §12.5). */
const ROOMY_PX = 190;

/**
 * Le panneau de droite (DESIGN §3, §12.5 ; body.html, lignes 159–209) : titre en Grenze Gotisch, résumé de la
 * file (« File d'attente · 8 titres · 47 min · fin vers 22 h 47 »), onglets à pilule glissante, deux volets
 * toujours montés (défilement gardé) qui se relaient : sortie 60 ms, entrée 140 ms (motion.md §6.14).
 * Styles : panel.css.
 */
export default function Sidebar({ booted = true }: { booted?: boolean }) {
  const [tab, setTab] = useState<Tab>('queue');
  const [roomy, setRoomy] = useState(false);
  const [, setMinute] = useState(0);
  const queue = useStore((s) => s.player.queue);
  const hasCurrent = useStore((s) => !!s.player.current);
  const paused = useStore((s) => s.player.paused);
  const tickBase = useStore((s) => s.tickBase);
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

  const onTabsKey = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next: Tab = (target.current ?? tab) === 'queue' ? 'hist' : 'queue';
    switchTo(next);
    panelRef.current?.querySelector<HTMLElement>(`#tab-${next}`)?.focus();
  };

  return (
    <aside className="panel" ref={panelRef} aria-label={tx('panel.label')} data-roomy={roomy}>
      <img className="minstrels" src="/gothique/minstrels-manesse-line.webp" alt="" aria-hidden="true" width={480} height={355} decoding="async"/>
      <div className="panel-head">
        <div className="ptitle-slot">
          <h2 className="ptitle" data-pane="queue" aria-hidden={tab !== 'queue'}>{t('queue.title')}</h2>
          <h2 className="ptitle" data-pane="hist" aria-hidden={tab !== 'hist'}>{t('history.title')}</h2>
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
        </div>
        {/* le résumé passe sous le titre ET les onglets : toute la largeur du panneau */}
        <div className="ptitle-slot psubs">
          <div className="psub tnum" data-pane="queue" aria-hidden={tab !== 'queue'}>{summary}</div>
          <div className="psub" data-pane="hist" aria-hidden={tab !== 'hist'}>{t('history.subtitle')}</div>
        </div>
      </div>
      <div className="panes">
        <div className="pane" id="pane-queue" role="tabpanel" aria-labelledby="tab-queue" data-pane="queue" aria-hidden={tab !== 'queue'}>
          <QueuePanel after={<Suggestions/>}/>
        </div>
        <div className="pane" id="pane-hist" role="tabpanel" aria-labelledby="tab-hist" data-pane="hist" aria-hidden={tab !== 'hist'}>
          <HistoryPanel/>
        </div>
      </div>
    </aside>
  );
}
