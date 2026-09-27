'use client';

import { useState } from 'react';
import { usePlayer, useStore } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { fmt } from '@/lib/format';
import { Ic } from '@/components/icons';

// ═══════════════════════════════
// History / Top Panel
// ═══════════════════════════════
export default function HistoryPanel() {
  const { historyItems, enqueue, refreshHistory, guildId } = usePlayer();
  const [mode, setMode] = useState<'top' | 'recent'>('top');
  const [loading, setLoading] = useState(false);

  const reload = async (m: 'top' | 'recent') => {
    setMode(m);
    setLoading(true);
    try {
      const s = useStore.getState();
      if (!s.guildId) return;
      const data = await api.getHistory(s.guildId, m, 30);
      useStore.getState().setHistoryItems(data?.items || []);
    } catch {} finally { setLoading(false); }
  };

  const quickAdd = (item: any) => {
    enqueue({
      query: item.url || item.title,
      url: item.url, title: item.title,
      artist: item.artist, thumb: item.thumb,
      duration: item.duration, provider: item.provider || 'youtube',
    }).catch(() => {}); // statut d'erreur déjà affiché par enqueue
  };

  if (!guildId) return <div className="text-sm text-txt-muted py-6 text-center opacity-50">Choisis un serveur</div>;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Mode toggle */}
      <div className="flex gap-1 mb-3 p-1 rounded-xl bg-surface-3 flex-shrink-0">
        <button onClick={() => reload('top')} className={`tab flex-1 text-center text-xs ${mode === 'top' ? 'tab-active' : ''}`}>
          Top joués
        </button>
        <button onClick={() => reload('recent')} className={`tab flex-1 text-center text-xs ${mode === 'recent' ? 'tab-active' : ''}`}>
          Récents
        </button>
        <button onClick={() => reload(mode)} disabled={loading}
          className={`tab text-xs px-2 ${loading ? 'loading-spin opacity-50' : ''}`}>
          ↻
        </button>
      </div>

      {/* Items */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1 max-[900px]:max-h-[40vh]">
        {!historyItems.length ? (
          <div className="text-center text-txt-muted text-sm py-8 opacity-40">
            <Ic icon="music" size={28}/><br/>
            <span className="mt-2 block">Aucun historique encore</span>
            <span className="text-xs block mt-1">Joue des morceaux pour les voir ici</span>
          </div>
        ) : historyItems.map((item, i) => (
          <div key={`${item.url}-${i}`} className="q-item group" onClick={() => quickAdd(item)}>
            <div className="relative">
              {item.thumb
                ? <div className="q-thumb" style={{ backgroundImage: `url("${item.thumb}")` }}/>
                : <div className="q-thumb flex items-center justify-center"><Ic icon="music" size={18}/></div>}
              {/* Play count badge */}
              {mode === 'top' && item.play_count > 1 && (
                <div className="absolute -top-1 -right-1 min-w-[18px] h-[18px] rounded-full bg-accent text-[10px] font-bold text-white flex items-center justify-center px-1">
                  {item.play_count}
                </div>
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate">{item.title || 'Titre inconnu'}</div>
              <div className="text-xs text-txt-muted truncate">
                {[
                  item.artist || '',
                  item.duration ? fmt(item.duration) : '',
                  item.last_played_by ? `par ${item.last_played_by}` : '',
                ].filter(Boolean).join(' · ')}
              </div>
            </div>
            <div className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-accent-dim hover:bg-accent/20 text-accent">
                <Ic icon="play" size={14}/>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
