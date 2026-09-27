'use client';

import { useId, useMemo, useRef } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { oftenAsked } from '@/lib/queue/view';
import { tx } from '@/theme/copy.extra';
import HistoryRow from './HistoryRow';
import { useRequeueList } from './useRequeue';

/**
 * « Souvent demandés ici », sous la file (DESIGN §12.5) : les trois titres les plus joués du serveur qui ne sont
 * ni en lecture ni dans la file, avec « + ». Clavier : celui des Annales (useRequeueList) ; la ligne remise quittant la
 * liste, Entrée passe le focus à sa voisine. Styles : history.css.
 */
export default function Suggestions() {
  const top = useStore((s) => s.historyItems);
  const queue = useStore((s) => s.player.queue);
  const currentUrl = useStore((s) => s.player.current?.url ?? null);
  const loggedIn = useStore((s) => !!s.me);
  const id = useId();
  const keysId = useId();
  const listRef = useRef<HTMLOListElement>(null);
  const pick = useMemo(() => oftenAsked(top, queue, currentUrl), [top, queue, currentUrl]);
  const list = useRequeueList(pick, listRef, true);   // la ligne remise part : Entrée passe à sa voisine
  if (!loggedIn || !pick.length) return null;
  return (
    <section className="sugg" aria-labelledby={id}>
      <div className="qlabel" id={id}>{tx('often.title')}</div>
      <ol className="qlist" ref={listRef} aria-labelledby={id} aria-describedby={keysId}
        onClick={list.onClick} onDoubleClick={list.onDoubleClick} onKeyDown={list.onKeyDown} onFocus={list.onFocus}>
        {pick.map((it) => (
          <HistoryRow key={it.url} item={it} rank={0} byName="" variant="srow" picked={list.picked === it.url}
            tabIndex={list.tabIndexOf(it.url || '')} meta={tx('history.plays', { n: it.play_count ?? 0 })}/>
        ))}
      </ol>
      <p id={keysId} className="sr">{tx('history.keys')}</p>
    </section>
  );
}
