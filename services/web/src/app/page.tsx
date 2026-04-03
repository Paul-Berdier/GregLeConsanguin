'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { usePlayer, usePlayerInit, useStore } from '@/hooks/usePlayer';
import { useProgress } from '@/hooks/useProgress';
import { api } from '@/lib/api';
import type { SearchResult } from '@/lib/types';

// ── Helpers ──
function fmt(sec?: number | null): string {
  if (sec == null || !isFinite(sec) || sec < 0) return '--:--';
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function extractVideoId(url?: string | null): string | null {
  if (!url) return null;
  const m = url.match(/(?:v=|\/shorts\/|youtu\.be\/)([A-Za-z0-9_\-]{11})/);
  return m ? m[1] : null;
}

function discordAvatar(me: any, size = 96): string | null {
  if (!me?.id) return null;
  if (me.avatar_url?.startsWith('http')) return me.avatar_url;
  if (me.avatar) return `https://cdn.discordapp.com/avatars/${me.id}/${me.avatar}.png?size=${size}`;
  // Default avatar index: (user_id >> 22) % 6
  let idx = 0;
  try { idx = Number((BigInt(me.id) >> 22n) % 6n); } catch { idx = parseInt(String(me.id).slice(-2), 10) % 6 || 0; }
  return `https://cdn.discordapp.com/embed/avatars/${idx}.png`;
}

// ── SVG Icons ──
const I = {
  play:   <path fill="currentColor" d="M8 5v14l11-7z"/>,
  pause:  <path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z"/>,
  skip:   <path fill="currentColor" d="M7 6v12l8.5-6zM17 6h2v12h-2z"/>,
  prev:   <path fill="currentColor" d="M7 6h2v12H7zm3 6l10 6V6z"/>,
  stop:   <path fill="currentColor" d="M6 6h12v12H6z"/>,
  repeat: <path fill="currentColor" d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z"/>,
  trash:  <path fill="currentColor" d="M9 3h6l1 2h5v2H3V5h5zm1 6h2v10h-2zm4 0h2v10h-2z"/>,
  search: <path fill="currentColor" d="M10 4a6 6 0 1 0 3.6 10.8l4.8 4.8 1.4-1.4-4.8-4.8A6 6 0 0 0 10 4zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"/>,
  music:  <path fill="currentColor" d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/>,
  video:  <path fill="currentColor" d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z"/>,
};
function Ic({ icon, size = 20 }: { icon: keyof typeof I; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} className="flex-shrink-0">{I[icon]}</svg>;
}

// ═══════════════════════════════
// Search Bar
// ═══════════════════════════════
function SearchBar() {
  const { enqueue } = usePlayer();
  const [q, setQ] = useState('');
  const [sugs, setSugs] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const timer = useRef<any>(null);
  const qRef = useRef('');

  const doSearch = useCallback(async (query: string) => {
    if (query.length < 2) { setSugs([]); setOpen(false); setSearching(false); return; }
    setSearching(true);
    try {
      const rows = await api.autocomplete(query, 6);
      if (qRef.current.trim() === query.trim() && Array.isArray(rows) && rows.length) {
        setSugs(rows); setOpen(true); setIdx(-1);
      } else if (qRef.current.trim() === query.trim()) { setSugs([]); setOpen(false); }
    } catch {} finally { setSearching(false); }
  }, []);

  const onInput = (v: string) => {
    setQ(v); qRef.current = v;
    clearTimeout(timer.current);
    if (v.trim().length < 2) { setSugs([]); setOpen(false); return; }
    setSearching(true);
    timer.current = setTimeout(() => doSearch(v.trim()), 280);
  };

  const submit = async (payload: Record<string, any>) => {
    setBusy(true); setOpen(false); setSugs([]); setQ('');
    try { await enqueue(payload); } finally { setBusy(false); }
  };

  const pick = (sug: SearchResult) => {
    const url = sug.webpage_url || sug.url || '';
    submit({ query: url || sug.title, url, webpage_url: url, title: sug.title,
      artist: sug.artist || sug.uploader || sug.channel, duration: sug.duration,
      thumb: sug.thumb || sug.thumbnail, thumbnail: sug.thumb || sug.thumbnail,
      source: sug.source || 'yt', provider: sug.provider || sug.source });
  };

  const go = () => {
    if (!q.trim()) return;
    idx >= 0 && sugs[idx] ? pick(sugs[idx]) : submit({ query: q.trim() });
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!open) { if (e.key === 'Enter') { e.preventDefault(); go(); } return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(sugs.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(-1, i - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); go(); }
    else if (e.key === 'Escape') setOpen(false);
  };

  return (
    <div className="relative flex-1 min-w-0">
      <div className="glass-subtle flex items-center gap-2 px-3 py-2">
        <div className={searching ? 'animate-spin opacity-50' : 'opacity-40'}><Ic icon="search" size={16}/></div>
        <input value={q} onChange={e => onInput(e.target.value)}
          onFocus={() => sugs.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          onKeyDown={onKey}
          placeholder="Rechercher un titre…"
          className="flex-1 bg-transparent border-none outline-none text-sm text-txt placeholder:text-txt-muted min-w-0 font-body"/>
        <button onClick={go} disabled={busy || !q.trim()}
          className={`btn-accent text-xs py-1.5 px-3 ${busy ? 'loading-spin opacity-60' : ''}`}>
          Ajouter
        </button>
      </div>
      {open && sugs.length > 0 && (
        <div className="sug-drop animate-fade-up">
          {sugs.map((s, i) => (
            <div key={`${s.url}-${i}`} className={`sug-item ${i === idx ? 'active' : ''}`}
              onMouseDown={e => e.preventDefault()} onClick={() => pick(s)} onMouseEnter={() => setIdx(i)}>
              {(s.thumb || s.thumbnail) && <div className="q-thumb" style={{ width: 40, height: 40, backgroundImage: `url("${s.thumb || s.thumbnail}")` }}/>}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate">{s.title}</div>
                <div className="text-xs text-txt-muted truncate">{s.artist || s.uploader || s.channel || ''}</div>
              </div>
              {s.duration != null && <span className="text-xs text-txt-muted font-mono">{fmt(s.duration)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════
// Video Player (YouTube embed)
// ═══════════════════════════════
function VideoPlayer() {
  const { player, togglePause, skip, stop, toggleRepeat, restartTrack } = usePlayer();
  const { progressRef, currentRef, totalRef } = useProgress();

  const cur = player.current;
  const videoId = extractVideoId(cur?.url);

  const [iframeStart, setIframeStart] = useState(0);
  const [iframeKey, setIframeKey] = useState('empty');

  const syncRef = useRef<{
    trackKey: string;
    pos: number;
    at: number;
    paused: boolean;
  }>({
    trackKey: '',
    pos: 0,
    at: 0,
    paused: true,
  });

  useEffect(() => {
    if (!videoId || !cur) {
      syncRef.current = {
        trackKey: '',
        pos: 0,
        at: 0,
        paused: true,
      };
      setIframeStart(0);
      setIframeKey('empty');
      return;
    }

    const now = Date.now();
    const trackKey = `${videoId}::${cur.url || ''}::${cur.title || ''}`;
    const incomingPos = Math.max(0, Math.floor(player.position || 0));
    const last = syncRef.current;

    const expectedPos = last.paused
      ? last.pos
      : last.pos + (now - last.at) / 1000;

    const drift = Math.abs(expectedPos - incomingPos);

    const shouldResync =
      last.trackKey !== trackKey ||       // nouveau morceau
      last.paused !== player.paused ||    // pause / reprise
      drift >= 2.5 ||                     // dérive détectée
      incomingPos === 0;                  // restart / début

    if (!shouldResync) {
      return;
    }

    syncRef.current = {
      trackKey,
      pos: incomingPos,
      at: now,
      paused: player.paused,
    };

    setIframeStart(incomingPos);
    setIframeKey(
      `${trackKey}:${incomingPos}:${player.paused ? 'pause' : 'play'}`
    );
  }, [videoId, cur?.url, cur?.title, player.position, player.paused]);

  const iframeSrc = videoId
    ? `https://www.youtube.com/embed/${videoId}?autoplay=${player.paused ? 0 : 1}&mute=1&controls=0&showinfo=0&rel=0&modestbranding=1&iv_load_policy=3&disablekb=1&playsinline=1&start=${iframeStart}`
    : null;

  return (
    <div className="flex flex-col gap-4 min-h-0 flex-1">
      <div className="video-frame">
        {videoId && iframeSrc ? (
          <iframe
            key={iframeKey}
            src={iframeSrc}
            allow="autoplay; encrypted-media"
            allowFullScreen
            title="YouTube video"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center z-[1]">
            {cur?.thumb ? (
              <>
                <div className="artwork-hero" style={{ backgroundImage: `url("${cur.thumb}")` }}/>
                <div className="artwork-center" style={{ backgroundImage: `url("${cur.thumb}")` }}/>
              </>
            ) : (
              <div className="flex flex-col items-center gap-3 opacity-30">
                <Ic icon="music" size={64}/>
                <span className="font-display text-lg">Rien en lecture</span>
              </div>
            )}
          </div>
        )}

        {cur && (
          <div className="absolute bottom-0 left-0 right-0 z-10 p-4 pb-3">
            <div className="flex items-end gap-3">
              <div className="flex-1 min-w-0">
                {!player.paused && (
                  <div className={`wave-bars mb-2 ${player.paused ? 'paused' : ''}`}>
                    <div className="wave-bar"/><div className="wave-bar"/><div className="wave-bar"/>
                    <div className="wave-bar"/><div className="wave-bar"/>
                  </div>
                )}
                <div className="font-display font-bold text-lg text-white truncate drop-shadow-lg">
                  {cur.title}
                </div>
                <div className="text-sm text-white/60 truncate">{cur.artist || '—'}</div>
                {cur.addedBy?.name && (
                  <div className="text-xs text-white/40 mt-0.5">par {cur.addedBy.name}</div>
                )}
              </div>

              {videoId && (
                <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white/10 backdrop-blur-sm text-xs text-white/70">
                  <Ic icon="video" size={14}/> Vidéo
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="px-1">
        <div className="progress-track">
          <div ref={progressRef} className="progress-fill" style={{ width: '0%' }}/>
        </div>
        <div className="flex justify-between mt-1 text-xs text-txt-muted font-mono">
          <span ref={currentRef}>0:00</span>
          <span ref={totalRef}>--:--</span>
        </div>
      </div>

      <div className="flex items-center justify-center gap-3">
        <button onClick={stop} className="ctrl" title="Stop"><Ic icon="stop" size={20}/></button>
        <button onClick={restartTrack} className="ctrl" title="Restart"><Ic icon="prev" size={20}/></button>
        <button onClick={togglePause} className="ctrl-main" title="Play/Pause">
          <Ic icon={player.paused ? 'play' : 'pause'} size={28}/>
        </button>
        <button onClick={skip} className="ctrl" title="Skip"><Ic icon="skip" size={20}/></button>
        <button onClick={toggleRepeat} className={`ctrl ${player.repeat ? 'ctrl-active' : ''}`} title="Repeat">
          <Ic icon="repeat" size={20}/>
        </button>
      </div>
    </div>
  );
}

// ═══════════════════════════════
// Queue Panel
// ═══════════════════════════════
function QueuePanel() {
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

// ═══════════════════════════════
// History / Top Panel
// ═══════════════════════════════
function HistoryPanel() {
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
    });
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
      <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1 max-[1100px]:max-h-[40vh]">
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

// ═══════════════════════════════
// Right Sidebar (tabs)
// ═══════════════════════════════
function Sidebar() {
  const [tab, setTab] = useState<'queue' | 'history'>('queue');

  return (
    <div className="glass flex flex-col h-full min-h-0 p-4 max-[1100px]:h-auto">
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

// ═══════════════════════════════
// Main Page
// ═══════════════════════════════
export default function Home() {
  usePlayerInit();
  const { me, guilds, guildId, socketReady, status, boot, setGuild, refreshMe } = usePlayer();
  const [booted, setBooted] = useState(false);

  useEffect(() => { boot().then(() => setBooted(true)).catch(() => setBooted(true)); }, [boot]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = async (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || (ev.target as HTMLElement)?.isContentEditable) return;
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

  useEffect(() => { const h = () => refreshMe().catch(() => {}); window.addEventListener('focus', h); return () => window.removeEventListener('focus', h); }, [refreshMe]);

  const avatar = discordAvatar(me, 96);
  const name = me?.global_name || me?.display_name || me?.username || '';

  return (
    <div className="relative z-10 flex flex-col h-[100dvh]" style={{ padding: 'calc(12px + env(safe-area-inset-top, 0px)) calc(12px + env(safe-area-inset-right, 0px)) calc(8px + env(safe-area-inset-bottom, 0px)) calc(12px + env(safe-area-inset-left, 0px))', gap: '12px' }}>

      {/* ═══ Header ═══ */}
      <header className="flex items-center gap-3 flex-shrink-0 flex-wrap">
        <div className="flex items-center gap-2.5 mr-2">
          <img src="/images/icon.png" alt="" className="w-8 h-8 rounded-xl border border-border object-cover"
            onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}/>
          <span className="font-display font-bold text-sm tracking-tight hidden sm:inline">Greg le Consanguin</span>
        </div>

        <SearchBar/>

        <div className="flex items-center gap-2">
          <select value={guildId} onChange={e => setGuild(e.target.value)}
            className="glass-subtle px-3 py-1.5 text-xs outline-none min-w-0 font-body">
            <option value="">Serveur…</option>
            {guilds.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>

          {me ? (
            <div className="flex items-center gap-2">
              {avatar && <img src={avatar} alt="" className="w-7 h-7 rounded-full border border-border"/>}
              <span className="text-xs text-txt-muted hidden md:inline">{name}</span>
              <button onClick={async () => {
                try { await api.logout(); window.location.reload(); } catch {} }}
                className="btn text-[11px] py-1">Déco</button>
            </div>
          ) : (
            <a href={api.getLoginUrl()} className="btn-accent text-xs">Connexion</a>
          )}

          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${socketReady ? 'bg-teal animate-pulse-ring' : 'bg-rose'}`}/>
        </div>
      </header>

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
  );
}
