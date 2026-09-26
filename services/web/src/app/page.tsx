'use client';

import { useState, useEffect } from 'react';
import { usePlayer, usePlayerInit, useStore } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { isShortcutIgnored } from '@/lib/playerUtils';
import Header from '@/components/Header/Header';
import VideoPlayer from '@/components/Stage/VideoPlayer';
import Sidebar from '@/components/Sidebar';

const FOCUS_REFRESH_MIN_MS = 15000;

// ═══════════════════════════════
// Main Page
// ═══════════════════════════════
export default function Home() {
  usePlayerInit();
  const { status, boot, refreshMe } = usePlayer();
  const [booted, setBooted] = useState(false);

  useEffect(() => { boot().then(() => setBooted(true)).catch(() => setBooted(true)); }, [boot]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = async (ev: KeyboardEvent) => {
      // Ctrl+R / Cmd+P… restent aux raccourcis du navigateur ; rien dans les champs / select / boutons (Espace)
      if (isShortcutIgnored(ev)) return;
      const s = useStore.getState();
      if (!s.me || !s.guildId) return;
      if (ev.code === 'Space') { ev.preventDefault(); s.setStatus('Pause…', 'info'); try { await api.togglePause(s.guildId, s.me.id); s.setStatus('OK ✅', 'ok'); } catch { s.setStatus('Erreur', 'err'); } }
      else if (ev.key === 'n') { try { await api.queueSkip(s.guildId, s.me.id); s.setStatus('Skip ✅', 'ok'); } catch {} }
      else if (ev.key === 'p') { try { await api.restart(s.guildId, s.me.id); } catch {} }
      else if (ev.key === 'r') { try { await api.repeat(s.guildId, s.me.id); } catch {} }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Retour sur l'onglet : on revérifie la session, au plus une fois toutes les 15 s et jamais en parallèle
  useEffect(() => {
    let last = 0, inFlight = false;
    const h = () => {
      const now = Date.now();
      if (inFlight || now - last < FOCUS_REFRESH_MIN_MS) return;
      last = now; inFlight = true;
      refreshMe().catch(() => {}).finally(() => { inFlight = false; });
    };
    window.addEventListener('focus', h);
    return () => window.removeEventListener('focus', h);
  }, [refreshMe]);

  return (
    <div className="relative z-10 flex flex-col h-[100dvh]">

      {/* ═══ Header ═══ (marges latérales : --page-x, header.css) */}
      <Header ready={booted}/>

      <div className="flex-1 min-h-0 flex flex-col" style={{
        padding: '0 calc(var(--page-x) + env(safe-area-inset-right, 0px)) calc(8px + env(safe-area-inset-bottom, 0px)) calc(var(--page-x) + env(safe-area-inset-left, 0px))',
        gap: '12px',
      }}>

        {/* ═══ Main ═══ */}
        <main className="flex-1 min-h-0 main-layout">
          {/* Left: Player */}
          <div className="glass p-4 flex flex-col min-h-0">
            <VideoPlayer/>
          </div>

          {/* Right: Sidebar */}
          <Sidebar/>
        </main>

        {/* ═══ Status ═══ */}
        <footer className="flex-shrink-0">
          <div className={`glass-subtle px-3 py-2 text-xs transition-all duration-300 ${
            status.kind === 'ok' ? 'status-ok' : status.kind === 'err' ? 'status-err' : ''}`}>
            <div className="flex items-center justify-between">
              <span className="text-txt-muted">{status.text}</span>
              <div className="hidden md:flex items-center gap-3 text-txt-dim text-[10px]">
                <span><kbd className="px-1 py-0.5 rounded border border-border text-[9px] font-mono">Space</kbd> Pause</span>
                <span><kbd className="px-1 py-0.5 rounded border border-border text-[9px] font-mono">N</kbd> Skip</span>
                <span><kbd className="px-1 py-0.5 rounded border border-border text-[9px] font-mono">P</kbd> Restart</span>
                <span><kbd className="px-1 py-0.5 rounded border border-border text-[9px] font-mono">R</kbd> Repeat</span>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
