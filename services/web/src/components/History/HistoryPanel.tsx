'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { playerActions, useStore } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { EASE, reducedMotion } from '@/lib/motion';
import { agoOf } from '@/lib/queue/view';
import type { HistoryItem } from '@/lib/queue/view';
import { seedOf } from '@/lib/stage/scene';
import { quip, t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import HistoryRow from './HistoryRow';
import { useRequeueList } from './useRequeue';

const REFRESH = <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 11a7.5 7.5 0 1 0-2.2 5.3"/><path d="M19.5 4.5V11H13"/></svg>;

/**
 * Les Annales (DESIGN §12.5, motion.md §6.15) : « Plus joués » (rangs, les trois premiers dorés) ou « Récents ».
 * « Plus joués » est la liste du store (usePlayer.refreshHistory, aussi lue par « Souvent demandés ici ») ;
 * « Récents » reste locale. Un clic sélectionne, un double-clic ou « + » remet le titre dans la file.
 * Le demandeur n'est nommé que s'il est connu : le Roi (« vous ») ou un courtisan présent dans la file.
 */
export default function HistoryPanel() {
  const guildId = useStore((s) => s.guildId);
  const top = useStore((s) => s.historyItems) as HistoryItem[];
  const meId = useStore((s) => s.me?.id ?? '');
  const queue = useStore((s) => s.player.queue);
  const current = useStore((s) => s.player.current);
  const [mode, setMode] = useState<'top' | 'recent'>('top');
  const [recent, setRecent] = useState<HistoryItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const refreshRef = useRef<HTMLButtonElement>(null);
  /** Numéro du dernier chargement, avancé aussi par un changement de serveur : une réponse dépassée ne s'écrit plus. */
  const seq = useRef(0);

  useEffect(() => { seq.current++; setMode('top'); setRecent(null); setLoading(false); }, [guildId]);

  const load = async (m: 'top' | 'recent') => {
    setMode(m);
    if (!guildId) return;
    const id = ++seq.current;
    const live = () => id === seq.current;
    setLoading(true);
    try {
      if (m === 'top') await playerActions.refreshHistory();
      else {
        const items = ((await api.getHistory(guildId, 'recent', 30))?.items || []) as HistoryItem[];
        if (live()) setRecent(items);
      }
    } catch {
      if (m === 'recent' && live()) setRecent([]);
    } finally {
      if (live()) setLoading(false);
    }
  };
  const refresh = () => {
    if (!reducedMotion()) refreshRef.current?.querySelector('svg')?.animate([{ transform: 'rotate(0)' }, { transform: 'rotate(360deg)' }], { duration: 500, easing: EASE.inOut });
    void load(mode);
  };

  const names = useMemo(() => {
    const out = new Map<string, string>();
    for (const x of [current, ...queue]) if (x?.addedBy?.id && x.addedBy.name) out.set(x.addedBy.id, x.addedBy.name);
    return out;
  }, [queue, current]);
  const nameOf = (id?: string) => (!id ? '' : id === meId ? t('history.mine') : names.get(id) || '');

  const items = mode === 'top' ? top : recent ?? [];
  const list = useRequeueList(items);
  const now = Date.now();
  const metaOf = (it: HistoryItem) => {
    if (mode === 'top') return tx('history.plays', { n: it.play_count ?? 0 });
    const ago = agoOf(it.last_played, now);
    return ago ? tx(`history.ago.${ago.unit}`, { n: ago.n }) : '';
  };

  if (!guildId) return <div className="hstate"><p>{t('history.noGuild')}</p></div>;

  return (
    <div className="hpane">
      <div className="seg">
        <button type="button" aria-pressed={mode === 'top'} onClick={() => void load('top')}>{t('history.segments.top')}</button>
        <button type="button" aria-pressed={mode === 'recent'} onClick={() => void load('recent')}>{t('history.segments.recent')}</button>
        <button type="button" className="refresh" ref={refreshRef} aria-label={t('history.refresh')} title={t('history.refresh')} onClick={refresh}>{REFRESH}</button>
      </div>
      <div className="scroller">
        {!items.length ? (
          loading || (mode === 'recent' && recent === null)
            ? <div className="hstate" role="status"><p>{t('history.loading.text')}</p></div>
            : <div className="hstate"><h4>{t('history.empty.title')}</h4><p>{t('history.empty.body')}</p>
              <div className="quip" aria-hidden="true">{quip('history.empty', seedOf(guildId))}</div></div>
        ) : (
          <ol className="qlist" aria-label={tx('history.list')} onClick={list.onClick} onDoubleClick={list.onDoubleClick}>
            {items.map((it, i) => (
              <HistoryRow key={`${it.url}-${i}`} item={it} rank={mode === 'top' ? i + 1 : 0} meta={metaOf(it)}
                byName={nameOf(it.last_played_by)} variant="hrow" picked={list.picked === it.url}/>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
