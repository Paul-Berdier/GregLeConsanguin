'use client';

import { useId, useMemo } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { oftenAsked } from '@/lib/queue/view';
import { tx } from '@/theme/copy.extra';
import HistoryRow from './HistoryRow';
import { useRequeueList } from './useRequeue';

/**
 * « Souvent demandés ici », sous la file (DESIGN §12.5) : les trois titres les plus joués du serveur qui ne sont
 * ni en lecture ni dans la file, avec « + ». Styles : history.css.
 */
export default function Suggestions() {
  const top = useStore((s) => s.historyItems);
  const queue = useStore((s) => s.player.queue);
  const currentUrl = useStore((s) => s.player.current?.url ?? null);
  const loggedIn = useStore((s) => !!s.me);
  const id = useId();
  const pick = useMemo(() => oftenAsked(top, queue, currentUrl), [top, queue, currentUrl]);
  const list = useRequeueList(pick);
  if (!loggedIn || !pick.length) return null;
  return (
    <section className="sugg" aria-labelledby={id}>
      <div className="qlabel" id={id}>{tx('often.title')}</div>
      <ol className="qlist" aria-labelledby={id} onClick={list.onClick} onDoubleClick={list.onDoubleClick}>
        {pick.map((it) => (
          <HistoryRow key={it.url} item={it} rank={0} byName="" variant="srow" picked={list.picked === it.url}
            meta={tx('history.plays', { n: it.play_count ?? 0 })}/>
        ))}
      </ol>
    </section>
  );
}
