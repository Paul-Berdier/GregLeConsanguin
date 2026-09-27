'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent, ReactNode } from 'react';
import { playerActions, useStore } from '@/hooks/usePlayer';
import { useFlip } from '@/hooks/useFlip';
import { livePosition } from '@/lib/playerUtils';
import { createDedupe, createSettle } from '@/lib/queue/drag';
import { queueEtas } from '@/lib/queue/view';
import { kingSealSrc, requesterOf, seedOf } from '@/lib/stage/scene';
import { kingName } from '@/components/Header/KingAvatar';
import { quip, t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import type { Track } from '@/lib/types';
import QueueRow from './QueueRow';
import { useQueueDrag } from './useQueueDrag';

/** Au-delà, la file se replie en « …et N autres titres » (tech.md §6.4). */
export const MAX_ROWS = 60;
/** Les heures estimées bougent à la minute : un rendu toutes les 30 s suffit. */
const ETA_REFRESH_MS = 30_000;
const keyOf = (x: Track) => x.key;

const GRIP_HINT = <svg viewBox="0 0 8 14" fill="currentColor" aria-hidden="true"><circle cx="2" cy="2" r="1.3"/><circle cx="6" cy="2" r="1.3"/><circle cx="2" cy="7" r="1.3"/><circle cx="6" cy="7" r="1.3"/><circle cx="2" cy="12" r="1.3"/><circle cx="6" cy="12" r="1.3"/></svg>;

/**
 * La file (spec §5, DESIGN §12.5) : un clic sélectionne, un double-clic ou ▶ joue maintenant (une fois par
 * 500 ms et par titre), ⤒ met en suivant, ✕ retire. Après un changement qui fait glisser les lignes sous le
 * pointeur, la liste s'accalmit (clics et puces ignorés 400 ms ou jusqu'à 3 px de mouvement).
 * Lignes animées par useFlip (entrées, sorties, FLIP) ; glisser par useQueueDrag. `after` : ce qui suit la
 * liste dans le défilement (« Souvent demandés ici », tâche 7). Styles : queue.css.
 */
export default function QueuePanel({ after }: { after?: ReactNode }) {
  const queue = useStore((s) => s.player.queue);
  const currentKey = useStore((s) => s.player.current?.key ?? null);
  const hasCurrent = useStore((s) => !!s.player.current);
  const paused = useStore((s) => s.player.paused);
  const tickBase = useStore((s) => s.tickBase);
  const me = useStore((s) => s.me);
  const [picked, setPicked] = useState<string | null>(null);
  const [, setMinute] = useState(0);
  const listRef = useRef<HTMLOListElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const settleRef = useRef(createSettle());
  const dedupeRef = useRef(createDedupe());

  useEffect(() => {
    const id = setInterval(() => setMinute((m) => m + 1), ETA_REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  // même tableau tant que la file ne change pas : useFlip compare `items` par référence (une tranche neuve à chaque rendu boucle)
  const shown = useMemo(() => (queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue), [queue]);
  // Un titre parti vers la scène (joué) sort à gauche ; un titre retiré, à droite.
  const exitDir = useCallback((key: string) => (key === currentKey ? -1 : 1) as 1 | -1, [currentKey]);
  const { rendered, freeze } = useFlip(listRef, shown, keyOf, { exitDir });

  const settle = useCallback(() => {
    const list = listRef.current;
    const s = settleRef.current;
    s.start(performance.now());
    list?.classList.add('settling');
    const done = () => { if (!s.active(performance.now())) list?.classList.remove('settling'); };
    const onMove = (e: PointerEvent) => { if (s.move(e.clientX, e.clientY, performance.now())) { done(); window.removeEventListener('pointermove', onMove); } };
    window.addEventListener('pointermove', onMove);
    setTimeout(() => { done(); window.removeEventListener('pointermove', onMove); }, 420);
  }, []);

  const drag = useQueueDrag({
    listRef, scrollRef, freeze, settle,
    order: rendered.map((p) => p.key).join('\n'),
    onLift: () => playerActions.setDragging(true),
    onEnd: () => playerActions.setDragging(false),
    // file repliée : déposé sous la dernière ligne visible = devant le premier titre caché (pas en fin de file)
    onDrop: (key, beforeKey) => playerActions.moveTrack(key, beforeKey ?? queue[MAX_ROWS]?.key ?? null),
  });

  const playNow = (key: string) => {
    if (dedupeRef.current(key, performance.now())) return;
    settle();
    void playerActions.playNow(key);
  };

  const rowOf = (e: MouseEvent) => {
    const li = (e.target as HTMLElement).closest<HTMLElement>('.row');
    return li && li.dataset.leaving == null && !settleRef.current.active(performance.now()) ? li.dataset.key || null : null;
  };
  const onClick = (e: MouseEvent) => {
    if (drag.swallowClick()) return;
    const key = rowOf(e);
    if (!key) return;
    const act = (e.target as HTMLElement).closest<HTMLElement>('[data-act]')?.dataset.act;
    if (act === 'del') { settle(); void playerActions.removeTrack(key); return; }
    if (act === 'next') { settle(); void playerActions.playNext(key); return; }
    if (act === 'play') { playNow(key); return; }
    setPicked(key);
  };
  const onDoubleClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest('[data-act], .grip')) return;
    const key = rowOf(e);
    if (key) playNow(key);
  };

  const remaining = hasCurrent ? Math.max(0, tickBase.dur - livePosition(tickBase, paused, performance.now())) : 0;
  const etas = new Map(queueEtas(shown, remaining).map((x) => [x.key, x]));
  const seal = me ? kingSealSrc(kingName(me)) : null;
  const empty = !rendered.length && !!me;

  return (
    <div className="qpane">
      <div className="scroller" ref={scrollRef}>
        {/* tout le contenu défilant dans un bloc : Sidebar mesure la place vide (les ménestrels) */}
        <div className="qcontent">
          <ol className="qlist" ref={listRef} aria-label={tx('queue.list')}
            onClick={onClick} onDoubleClick={onDoubleClick} onPointerDown={drag.onPointerDown}>
            {rendered.map(({ key, item, leaving }) => {
              const eta = etas.get(key);
              const mine = requesterOf(item.addedBy, me?.id).kind === 'mine';
              return (
                <QueueRow key={key} item={item} leaving={leaving} picked={picked === key} next={!!eta?.next}
                  eta={!eta ? '' : eta.next ? tx('queue.etaNext') : eta.mins == null ? '' : tx('queue.eta', { n: eta.mins })}
                  sealSrc={mine ? seal : null}/>
              );
            })}
            {queue.length > MAX_ROWS && <li className="more-row">{tx('queue.more', { n: queue.length - MAX_ROWS })}</li>}
          </ol>
          {empty && (
            <div className="qempty">
              <h4>{t('queue.empty.flavorTitle')}</h4>
              <p>{t('queue.empty.body')}</p>
              <div className="quip" aria-hidden="true">{quip('queue.empty', seedOf(me?.id || ''))}</div>
            </div>
          )}
          {after}
        </div>
      </div>
      <div className="panel-foot">
        <span className="hint" data-shown={queue.length >= 2}>{GRIP_HINT}{t('queue.dnd.hint')}</span>
      </div>
    </div>
  );
}
