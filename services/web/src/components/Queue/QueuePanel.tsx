'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { MouseEvent, ReactNode } from 'react';
import { playerActions, useStore } from '@/hooks/usePlayer';
import { useFlip } from '@/hooks/useFlip';
import { useRoving } from '@/hooks/useRoving';
import { moveBefore } from '@/lib/keys';
import { livePosition } from '@/lib/playerUtils';
import { createDedupe, createSettle } from '@/lib/queue/drag';
import { sealBook } from '@/lib/queue/seal';
import { queueEtas } from '@/lib/queue/view';
import { kingOrders } from '@/lib/stage/coronation';
import type { Via } from '@/lib/stage/coronation';
import { kingSealSrc, requesterOf, seedOf } from '@/lib/stage/scene';
import { parseTitle } from '@/lib/titles';
import { kingName } from '@/components/Header/KingAvatar';
import { speak } from '@/components/Herald/store';
import { quip, t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import type { Track } from '@/lib/types';
import QueueRow from './QueueRow';
import { stampRow } from './seal';
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
 * Étape 4 : l'ajout du Roi attendu (sealBook) entre avec Le Sceau (seal.ts) ; la file vidée d'un coup (arrêt) sort
 * de la dernière ligne à la première ; « jouer maintenant » note l'ordre du Roi (kingOrders) pour la scène.
 * Clavier (useRoving) : un arrêt de Tab, ↑ ↓ Début Fin, Entrée, Suppr, Alt+↑ ↓ (déplacement annoncé), Alt+Début.
 */
export default function QueuePanel({ after }: { after?: ReactNode }) {
  const queue = useStore((s) => s.player.queue);
  const currentKey = useStore((s) => s.player.current?.key ?? null);
  const hasCurrent = useStore((s) => !!s.player.current);
  const paused = useStore((s) => s.player.paused);
  const tickBase = useStore((s) => s.tickBase);
  const me = useStore((s) => s.me);
  const [picked, setPicked] = useState<string | null>(null);
  const seal = me ? kingSealSrc(kingName(me)) : null;
  const [, setMinute] = useState(0);
  const listRef = useRef<HTMLOListElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const settleRef = useRef(createSettle());
  const dedupeRef = useRef(createDedupe());
  const keysId = useId();

  useEffect(() => {
    const id = setInterval(() => setMinute((m) => m + 1), ETA_REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  // même tableau tant que la file ne change pas : useFlip compare `items` par référence (une tranche neuve à chaque rendu boucle)
  const shown = useMemo(() => (queue.length > MAX_ROWS ? queue.slice(0, MAX_ROWS) : queue), [queue]);
  // Un titre parti vers la scène (joué) sort à gauche ; un titre retiré, à droite.
  const exitDir = useCallback((key: string) => (key === currentKey ? -1 : 1) as 1 | -1, [currentKey]);
  const qKeys = useMemo(() => queue.map(keyOf), [queue]);
  const shownKeys = useMemo(() => shown.map(keyOf), [shown]);
  const byKey = useRef(new Map<string, Track>()); byKey.current = new Map(queue.map((x) => [x.key, x]));
  const meRef = useRef(me); meRef.current = me;
  const onEnter = useCallback((key: string, el: HTMLElement) => {   // Le Sceau : l'ajout du Roi attendu
    const item = byKey.current.get(key);
    if (!item) return false;
    const mine = requesterOf(item.addedBy, meRef.current?.id).kind === 'mine';
    const w = sealBook.take({ url: item.url, mine }, performance.now());
    if (w) stampRow(el, w);
    return !!w;
  }, []);
  const { rendered, freeze } = useFlip(listRef, shown, keyOf, { exitDir, exitStagger: shown.length === 0, onEnter });

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

  /** false : le même titre vient d'être lancé (moins de 500 ms), rien n'est joué. */
  const playNow = (key: string, via: Via): boolean => {
    if (dedupeRef.current(key, performance.now())) return false;
    kingOrders.mark(key, via, performance.now());
    settle();
    void playerActions.playNow(key);
    return true;
  };
  const songOf = (x: Track) => parseTitle(x.title, x.artist).song || x.title;
  /** Alt+↑↓ : seul le dernier déplacement est annoncé (un précédent, remplacé ou accusé en retard, dirait une place dépassée). */
  const moves = useRef(0);
  const roving = useRoving(listRef, shownKeys, 'key', (act, key, i) => {
    const near = shownKeys[i + 1] ?? shownKeys[i - 1] ?? null;
    if (act.kind === 'activate') return playNow(key, 'key') ? near : null;
    if (act.kind === 'remove') { settle(); void playerActions.removeTrack(key); return near; }
    if (act.kind === 'next') { void playerActions.playNext(key); return undefined; }
    const before = moveBefore(qKeys, key, act.dir), item = queue[i];
    if (before === undefined || !item) return undefined;
    const n = ++moves.current;
    void playerActions.moveTrack(key, before).then((ok) => {
      if (ok && n === moves.current) speak(t('queue.dnd.liveMoved', { title: songOf(item), pos: i + 1 + act.dir, total: queue.length }));
    });
    return undefined;
  });

  // Sceau du Roi décodé au premier temps mort : prêt quand son ajout le pose (les lignes le chargent en différé).
  useEffect(() => {
    if (!seal) return;
    let cancelled = false;
    const decode = () => { if (cancelled) return; const im = new Image(); im.src = seal; im.decode().catch(() => {}); };
    const idle = typeof window.requestIdleCallback === 'function';
    const id = idle ? window.requestIdleCallback(decode) : window.setTimeout(decode, 1000);
    return () => { cancelled = true; if (idle) window.cancelIdleCallback(id); else window.clearTimeout(id); };
  }, [seal]);

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
    if (act === 'play') { playNow(key, 'pointer'); return; }
    setPicked(key);
  };
  const onDoubleClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest('[data-act], .grip')) return;
    const key = rowOf(e);
    if (key) playNow(key, 'pointer');
  };

  const remaining = hasCurrent ? Math.max(0, tickBase.dur - livePosition(tickBase, paused, performance.now())) : 0;
  const etas = new Map(queueEtas(shown, remaining).map((x) => [x.key, x]));
  const empty = !rendered.length && !!me;

  return (
    <div className="qpane">
      <div className="scroller" ref={scrollRef}>
        {/* tout le contenu défilant dans un bloc : Sidebar mesure la place vide (les ménestrels) */}
        <div className="qcontent">
          <ol className="qlist" ref={listRef} aria-label={tx('queue.list')} aria-describedby={keysId}
            onClick={onClick} onDoubleClick={onDoubleClick} onPointerDown={drag.onPointerDown}
            onKeyDown={roving.onKeyDown} onFocus={roving.onFocus}>
            {rendered.map(({ key, item, leaving }) => {
              const eta = etas.get(key);
              const mine = requesterOf(item.addedBy, me?.id).kind === 'mine';
              return (
                <QueueRow key={key} item={item} leaving={leaving} picked={picked === key} next={!!eta?.next}
                  tabIndex={leaving ? -1 : roving.tabIndexOf(key)}
                  eta={!eta ? '' : eta.next ? tx('queue.etaNext') : eta.mins == null ? '' : tx('queue.eta', { n: eta.mins })}
                  sealSrc={mine ? seal : null}/>
              );
            })}
            {queue.length > MAX_ROWS && <li className="more-row">{tx('queue.more', { n: queue.length - MAX_ROWS })}</li>}
          </ol>
          <p id={keysId} className="sr">{tx('queue.keys')}</p>
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
