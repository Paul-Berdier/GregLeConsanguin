'use client';

import { useState } from 'react';
import QueuePanel from '@/components/Queue/QueuePanel';
import HistoryPanel from '@/components/History/HistoryPanel';

// ═══════════════════════════════
// Right Sidebar (tabs)
// ═══════════════════════════════
export default function Sidebar() {
  const [tab, setTab] = useState<'queue' | 'history'>('queue');

  return (
    <div className="glass flex flex-col h-full min-h-0 p-4 max-[900px]:h-auto">
      {/* Tab bar */}
      <div className="flex gap-1 mb-4 p-1 rounded-xl bg-surface-3 flex-shrink-0">
        <button onClick={() => setTab('queue')} className={`tab flex-1 text-center ${tab === 'queue' ? 'tab-active' : ''}`}>
          File d&apos;attente
        </button>
        <button onClick={() => setTab('history')} className={`tab flex-1 text-center ${tab === 'history' ? 'tab-active' : ''}`}>
          Historique
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'queue' ? <QueuePanel/> : <HistoryPanel/>}
      </div>
    </div>
  );
}
