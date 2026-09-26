'use client';

import { usePlayer } from '@/hooks/usePlayer';
import { fmt } from '@/lib/format';
import { Ic } from '@/components/icons';

// ═══════════════════════════════
// Queue Panel
// ═══════════════════════════════
export default function QueuePanel() {
  const { player, removeFromQueue, playAt } = usePlayer();
  const q = player.queue;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between mb-3 flex-shrink-0">
        <span className="font-display font-bold text-sm">File d&apos;attente</span>
        <span className="text-xs text-txt-muted font-mono">{q.length} titre{q.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1 max-[1100px]:max-h-[40vh]">
        {!q.length ? (
          <div className="text-center text-txt-muted text-sm py-8 opacity-50">
            <Ic icon="music" size={32}/><br/>File vide
          </div>
        ) : q.map((item, i) => (
          <div key={`${item.url}-${i}`} className="q-item group" onClick={() => playAt(i)}>
            {item.thumb && <div className="q-thumb" style={{ backgroundImage: `url("${item.thumb}")` }}/>}
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate">{item.title || 'Titre inconnu'}</div>
              <div className="text-xs text-txt-muted truncate">
                {[item.artist, item.duration != null ? fmt(item.duration) : '', item.addedBy?.name ? `par ${item.addedBy.name}` : ''].filter(Boolean).join(' · ')}
              </div>
            </div>
            <button onClick={e => { e.stopPropagation(); removeFromQueue(i); }}
              className="opacity-0 group-hover:opacity-100 transition-opacity w-8 h-8 rounded-lg flex items-center justify-center bg-rose-dim hover:bg-rose/20 text-rose"
              title="Retirer"><Ic icon="trash" size={14}/></button>
          </div>
        ))}
      </div>
    </div>
  );
}
