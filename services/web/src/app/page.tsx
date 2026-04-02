'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { randomQuote } from '@/theme/greg-quotes';
import type { SearchResult, GuildInfo } from '@/lib/types';

function formatTime(sec?: number): string {
  if (sec == null || sec < 0) return '--:--';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// ─── Search Bar ───
function SearchBar({ onAdd }: { onAdd: (q: string, meta?: any) => void }) {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<SearchResult[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const debounce = useRef<any>(null);

  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setSuggestions([]); return; }
    const res = await api.autocomplete(q, 6);
    if (res.ok && res.results) setSuggestions(res.results);
  }, []);

  const handleInput = (val: string) => {
    setQuery(val);
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => search(val), 300);
  };

  const submit = (q: string, meta?: any) => {
    onAdd(q, meta);
    setQuery('');
    setSuggestions([]);
    setShowSuggestions(false);
  };

  return (
    <div className="relative flex-1 max-w-xl">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => setShowSuggestions(true)}
          onKeyDown={(e) => e.key === 'Enter' && query && submit(query)}
          placeholder="Rechercher une complainte…"
          className="flex-1 bg-parchment-800/60 border border-gold/20 rounded-medieval px-4 py-2 text-parchment-200 placeholder:text-parchment-500 focus:outline-none focus:border-gold/50 text-sm"
        />
        <button onClick={() => query && submit(query)} className="btn-primary text-sm">
          Ajouter
        </button>
      </div>
      {showSuggestions && suggestions.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 card-medieval z-50 max-h-64 overflow-y-auto">
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => submit(s.url, { title: s.title, thumb: s.thumb, duration: s.duration, artist: s.artist })}
              className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gold/10 transition-colors text-left"
            >
              {s.thumb && (
                <img src={s.thumb} alt="" className="w-10 h-10 rounded object-cover flex-shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-sm text-parchment-200 truncate">{s.title}</div>
                <div className="text-xs text-parchment-500">{s.artist} · {formatTime(s.duration)}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Now Playing ───
function NowPlaying({ state, onPause, onSkip, onStop, onRepeat }: any) {
  const cur = state.current;
  if (!cur) {
    return (
      <div className="card-medieval p-6 text-center text-parchment-500">
        <div className="greg-title text-xl mb-2">Silence…</div>
        <p className="text-sm">La file est vide. Ajoutez un morceau pour réveiller Greg.</p>
      </div>
    );
  }

  const thumb = cur.thumb || cur.thumbnail || state.thumbnail;
  const pct = state.duration ? Math.min(100, (state.position / state.duration) * 100) : 0;

  return (
    <div className="card-medieval p-5">
      <div className="text-xs text-gold/60 uppercase tracking-wider mb-3 font-semibold">En cours</div>
      <div className="flex gap-4">
        {thumb && (
          <img src={thumb} alt="" className="w-20 h-20 rounded-medieval object-cover shadow-lg flex-shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="text-lg font-semibold text-parchment-100 truncate">{cur.title}</div>
          {cur.artist && <div className="text-sm text-parchment-400 truncate">{cur.artist}</div>}
          {state.requested_by_user && (
            <div className="text-xs text-parchment-500 mt-1">
              Demandé par {state.requested_by_user.display_name}
            </div>
          )}
        </div>
      </div>

      {/* Progress */}
      <div className="mt-4">
        <div className="progress-bar-track">
          <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex justify-between text-xs text-parchment-500 mt-1">
          <span>{formatTime(state.position)}</span>
          <span>{formatTime(state.duration)}</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center gap-3 mt-4">
        <button onClick={onPause} className="btn-medieval w-10 h-10 flex items-center justify-center text-lg" title={state.paused ? 'Reprendre' : 'Pause'}>
          {state.paused ? '▶' : '⏸'}
        </button>
        <button onClick={onSkip} className="btn-medieval w-10 h-10 flex items-center justify-center text-lg" title="Skip">
          ⏭
        </button>
        <button onClick={onStop} className="btn-medieval w-10 h-10 flex items-center justify-center text-lg" title="Stop">
          ⏹
        </button>
        <button
          onClick={onRepeat}
          className={`btn-medieval w-10 h-10 flex items-center justify-center text-lg ${state.repeat_all ? 'bg-gold/30 border-gold/50' : ''}`}
          title="Repeat"
        >
          🔁
        </button>
      </div>
    </div>
  );
}

// ─── Queue ───
function Queue({ queue, onRemove }: { queue: any[]; onRemove: (i: number) => void }) {
  if (!queue.length) return null;

  // Chiffres romains pour le style
  const roman = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X',
    'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX'];

  return (
    <div className="card-medieval p-4">
      <div className="text-xs text-gold/60 uppercase tracking-wider mb-3 font-semibold">
        📜 File d'attente ({queue.length} complainte{queue.length > 1 ? 's' : ''})
      </div>
      <div className="space-y-1 max-h-[40vh] overflow-y-auto">
        {queue.map((item, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-2 rounded hover:bg-gold/5 transition-colors group">
            <span className="text-xs text-gold/40 font-medieval w-6 text-right flex-shrink-0">
              {roman[i] || i + 1}
            </span>
            {(item.thumb || item.thumbnail) && (
              <img src={item.thumb || item.thumbnail} alt="" className="w-8 h-8 rounded object-cover flex-shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <div className="text-sm text-parchment-200 truncate">{item.title}</div>
              <div className="text-xs text-parchment-500">{item.artist || ''} · {formatTime(item.duration)}</div>
            </div>
            <button
              onClick={() => onRemove(i)}
              className="opacity-0 group-hover:opacity-100 text-crimson-light hover:text-crimson text-sm transition-opacity"
              title="Supprimer"
            >
              🗑
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Page ───
export default function Home() {
  const {
    state, guildId, userId, connected,
    setGuild, setUser, enqueue, skip, stop, togglePause, repeat, remove,
  } = usePlayer();

  const [guilds, setGuilds] = useState<GuildInfo[]>([]);
  const [user, setUserData] = useState<any>(null);
  const [quote] = useState(randomQuote);

  // Load user & guilds on mount
  useEffect(() => {
    api.getMe().then((res) => {
      if (res.ok && res.user) {
        setUserData(res.user);
        setUser(res.user.id);
      }
    });
    api.getGuilds().then((res) => {
      if (res.ok && res.guilds) setGuilds(res.guilds);
    });

    // Restore guild from localStorage
    const saved = typeof window !== 'undefined' ? localStorage.getItem('greg.guild_id') : null;
    if (saved) setGuild(saved);
  }, []);

  const handleGuildChange = (id: string) => {
    setGuild(id);
    if (typeof window !== 'undefined') localStorage.setItem('greg.guild_id', id);
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center gap-4 px-6 py-3 border-b border-gold/10 bg-parchment-900/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gold/20 flex items-center justify-center text-lg">👑</div>
          <div>
            <div className="greg-title text-lg leading-tight">Greg le Consanguin</div>
            <div className="text-xs text-parchment-500">Web Player</div>
          </div>
        </div>

        <SearchBar onAdd={(q, meta) => enqueue(q, meta)} />

        <div className="flex items-center gap-3 ml-auto">
          <select
            value={guildId}
            onChange={(e) => handleGuildChange(e.target.value)}
            className="bg-parchment-800/60 border border-gold/20 rounded-medieval px-3 py-1.5 text-sm text-parchment-300 focus:outline-none focus:border-gold/50"
          >
            <option value="">Serveur…</option>
            {guilds.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>

          {user ? (
            <div className="flex items-center gap-2">
              {user.avatar && (
                <img
                  src={`https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=32`}
                  alt="" className="w-7 h-7 rounded-full"
                />
              )}
              <span className="text-sm text-parchment-300">{user.global_name || user.username}</span>
            </div>
          ) : (
            <a href="/api/v1/auth/login" className="btn-medieval text-xs">Se connecter</a>
          )}

          <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald' : 'bg-crimson'}`} title={connected ? 'Connecté' : 'Déconnecté'} />
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden px-6 py-4">
        <div className="max-w-2xl mx-auto space-y-4 h-full flex flex-col">
          <NowPlaying
            state={state}
            onPause={togglePause}
            onSkip={skip}
            onStop={stop}
            onRepeat={repeat}
          />

          <div className="flex-1 overflow-hidden">
            <Queue queue={state.queue} onRemove={remove} />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-6 py-2 border-t border-gold/10 bg-parchment-900/60 text-center flex-shrink-0">
        <p className="text-xs text-parchment-500 italic">
          💬 "{quote}" — Greg le Consanguin
        </p>
      </footer>
    </div>
  );
}
