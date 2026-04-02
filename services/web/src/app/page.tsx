'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { usePlayer, useStore } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { randomQuote } from '@/theme/greg-quotes';
import type { SearchResult, SpotifyPlaylist, SpotifyTrack } from '@/lib/types';

// ── Helpers ──
function formatTime(sec?: number | null): string {
  if (sec == null || !isFinite(sec) || sec < 0) return '--:--';
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

function defaultDiscordAvatarIndex(id: unknown): number {
  const digits = String(id ?? '').replace(/\D/g, '');
  if (!digits) return 0;

  let acc = 0;
  for (let i = 0; i < digits.length; i += 1) {
    acc = (acc * 31 + Number(digits[i])) % 6;
  }
  return acc;
}

function discordAvatarUrl(me: any, size = 96): string | null {
  if (!me?.id) return null;

  if (
    me.avatar_url &&
    typeof me.avatar_url === 'string' &&
    me.avatar_url.startsWith('http')
  ) {
    return me.avatar_url;
  }

  if (me.avatar) {
    return `https://cdn.discordapp.com/avatars/${me.id}/${me.avatar}.png?size=${size}`;
  }

  const idx = defaultDiscordAvatarIndex(me.id);
  return `https://cdn.discordapp.com/embed/avatars/${idx}.png`;
}

// ── Icons (SVG inline) ──
const Icons = {
  play: <path fill="currentColor" d="M8 5v14l11-7z" />,
  pause: <path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z" />,
  skip: <path fill="currentColor" d="M7 6v12l8.5-6zM17 6h2v12h-2z" />,
  prev: <path fill="currentColor" d="M7 6h2v12H7zm3 6l10 6V6z" />,
  stop: <path fill="currentColor" d="M6 6h12v12H6z" />,
  repeat: (
    <path
      fill="currentColor"
      d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z"
    />
  ),
  trash: <path fill="currentColor" d="M9 3h6l1 2h5v2H3V5h5zm1 6h2v10h-2zm4 0h2v10h-2z" />,
  search: (
    <path
      fill="currentColor"
      d="M10 4a6 6 0 1 0 3.6 10.8l4.8 4.8 1.4-1.4-4.8-4.8A6 6 0 0 0 10 4zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"
    />
  ),
  user: (
    <path
      fill="currentColor"
      d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4zm0 2c-4.4 0-8 2.2-8 5v1h16v-1c0-2.8-3.6-5-8-5z"
    />
  ),
};

function Icon({ icon, size = 18 }: { icon: keyof typeof Icons; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className="flex-shrink-0">
      {Icons[icon]}
    </svg>
  );
}

// ═══════════════════════════════════════════
// Search Bar
// ═══════════════════════════════════════════
function SearchBar() {
  const { enqueue } = usePlayer();
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<SearchResult[]>([]);
  const [showSugs, setShowSugs] = useState(false);
  const [sugIdx, setSugIdx] = useState(-1);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSuggestions([]);
      setShowSugs(false);
      return;
    }

    try {
      const rows = await api.autocomplete(q, 8);

      if (Array.isArray(rows)) {
        setSuggestions(rows);
        setShowSugs(rows.length > 0);
        setSugIdx(-1);
      } else {
        setSuggestions([]);
        setShowSugs(false);
      }
    } catch {
      setSuggestions([]);
      setShowSugs(false);
    }
  }, []);

  const handleInput = (val: string) => {
    setQuery(val);

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      fetchSuggestions(val);
    }, 180);
  };

  const submit = async (rawQuery: string, meta?: Record<string, any>) => {
    if (!rawQuery.trim()) return;

    setLoading(true);
    setShowSugs(false);
    setSuggestions([]);
    setQuery('');

    try {
      await enqueue({
        query: rawQuery,
        ...meta,
      });
    } finally {
      setLoading(false);
    }
  };

  const submitFromSuggestion = (sug: SearchResult) => {
    const url = sug.webpage_url || sug.url || '';
    const title = sug.title || '';

    submit(url || title, {
      title: title || undefined,
      artist: sug.artist || sug.uploader || sug.channel || undefined,
      duration: sug.duration ?? undefined,
      thumb: sug.thumb || sug.thumbnail || undefined,
      thumbnail: sug.thumb || sug.thumbnail || undefined,
      source: sug.source || sug.provider || 'yt',
      provider: sug.provider || sug.source || undefined,
      webpage_url: url || undefined,
      url: url || undefined,
    });
  };

  const submitRaw = () => {
    if (!query.trim()) return;

    if (sugIdx >= 0 && suggestions[sugIdx]) {
      submitFromSuggestion(suggestions[sugIdx]);
    } else {
      submit(query.trim());
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showSugs) {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitRaw();
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSugIdx((i) => Math.min(suggestions.length - 1, i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSugIdx((i) => Math.max(-1, i - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      submitRaw();
    } else if (e.key === 'Escape') {
      setShowSugs(false);
    }
  };

  return (
    <div className="relative flex-1 min-w-0" style={{ minWidth: '280px' }}>
      <div className="card-greg flex items-center gap-2.5 px-3 py-2.5">
        <Icon icon="search" />
        <input
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => {
            if (suggestions.length) setShowSugs(true);
          }}
          onBlur={() => setTimeout(() => setShowSugs(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder="Rechercher YouTube..."
          className="flex-1 bg-transparent border-none outline-none text-txt text-sm placeholder:text-muted min-w-0"
        />
        <button
          onClick={submitRaw}
          disabled={loading || !query.trim()}
          className={`btn-primary text-sm ${loading ? 'btn-loading' : ''}`}
        >
          Ajouter
        </button>
      </div>

      {showSugs && suggestions.length > 0 && (
        <div className="suggestion-dropdown animate-fade-in">
          {suggestions.map((sug, i) => (
            <div
              key={`${sug.url || sug.title || 'sug'}-${i}`}
              className={`suggestion-item ${i === sugIdx ? 'active' : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => submitFromSuggestion(sug)}
              onMouseEnter={() => setSugIdx(i)}
            >
              {(sug.thumb || sug.thumbnail) && (
                <div
                  className="queue-thumb"
                  style={{
                    width: 42,
                    height: 42,
                    backgroundImage: `url("${sug.thumb || sug.thumbnail}")`,
                  }}
                />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-bold text-txt truncate">{sug.title}</div>
                <div className="text-xs text-muted truncate">
                  {sug.artist || sug.uploader || sug.channel || ''}
                </div>
              </div>
              {sug.duration != null && (
                <span className="text-xs text-muted flex-shrink-0">
                  {formatTime(sug.duration)}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// Now Playing
// ═══════════════════════════════════════════
function NowPlaying() {
  const { player, togglePause, skip, stop, toggleRepeat, restartTrack } = usePlayer();
  const cur = player.current;

  const dur = player.duration || cur?.duration || 0;
  const pct = dur > 0 ? Math.min(100, (player.position / dur) * 100) : 0;

  return (
    <div className="card-greg p-[18px] flex flex-col gap-3.5 h-full min-h-0 overflow-hidden">
      <div className="self-center flex-shrink-0">
        <div
          className="rounded-[18px] border border-stroke shadow-greg"
          style={{
            width: 'clamp(140px, 14vw, 220px)',
            height: 'clamp(140px, 14vw, 220px)',
            background: cur?.thumb
              ? `url("${cur.thumb}") center/cover no-repeat`
              : 'rgba(15, 23, 42, 0.7)',
            boxShadow: cur?.thumb ? '0 16px 48px rgba(0,0,0,0.5)' : undefined,
          }}
        />
      </div>

      <div className="min-w-0 w-full text-center">
        <div className="font-black text-xl text-txt truncate">
          {cur?.title || 'Rien en cours'}
        </div>
        <div className="text-sm text-muted mt-1 truncate">{cur?.artist || '-'}</div>
        {cur?.addedBy?.name && (
          <div className="text-xs text-muted/70 mt-1">Demande par {cur.addedBy.name}</div>
        )}
      </div>

      <div className="w-full mt-1">
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex justify-between mt-1.5 text-xs text-muted">
          <span>{formatTime(player.position)}</span>
          <span>{formatTime(dur)}</span>
        </div>
      </div>

      <div className="flex items-center justify-center gap-2.5 mt-auto pt-2">
        <button onClick={stop} className="control-btn" title="Stop">
          <Icon icon="stop" size={22} />
        </button>
        <button onClick={restartTrack} className="control-btn" title="Restart">
          <Icon icon="prev" size={22} />
        </button>
        <button onClick={togglePause} className="control-btn-primary" title="Play / Pause">
          <Icon icon={player.paused ? 'play' : 'pause'} size={28} />
        </button>
        <button onClick={skip} className="control-btn" title="Skip">
          <Icon icon="skip" size={22} />
        </button>
        <button
          onClick={toggleRepeat}
          className={`control-btn ${player.repeat ? 'control-btn-active' : ''}`}
          title="Repeat"
        >
          <Icon icon="repeat" size={22} />
        </button>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// Queue
// ═══════════════════════════════════════════
function Queue() {
  const { player, removeFromQueue, playAt } = usePlayer();
  const q = player.queue;

  return (
    <div className="card-greg p-3.5 flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex items-center justify-between mb-2.5 flex-shrink-0">
        <div className="font-black text-sm">File d&apos;attente</div>
        <div className="text-xs text-muted">
          {q.length} titre{q.length > 1 ? 's' : ''}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-1 max-[1100px]:max-h-[50vh] max-[1100px]:flex-none">
        {q.length === 0 ? (
          <div className="queue-empty text-sm">File d&apos;attente vide</div>
        ) : (
          q.map((item, i) => (
            <div
              key={`${item.url || item.title || 'track'}-${i}`}
              className="queue-item group"
              onClick={() => playAt(i)}
            >
              {item.thumb && (
                <div
                  className="queue-thumb"
                  style={{ backgroundImage: `url("${item.thumb}")` }}
                />
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-bold text-txt truncate">
                  {item.title || 'Titre inconnu'}
                </div>
                <div className="text-xs text-muted truncate">
                  {[item.artist, item.duration != null ? formatTime(item.duration) : '', item.addedBy?.name ? `par ${item.addedBy.name}` : '']
                    .filter(Boolean)
                    .join(' • ')}
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  removeFromQueue(i);
                }}
                className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 w-[38px] h-[38px] rounded-[14px] border border-danger/30 bg-danger/10 hover:bg-danger/20 flex items-center justify-center text-txt"
                title="Retirer"
              >
                <Icon icon="trash" size={16} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// Spotify Panel
// ═══════════════════════════════════════════
function SpotifyPanel() {
  const {
    me,
    spotifyLinked,
    spotifyProfile,
    spotifyPlaylists,
    spotifyTracks,
    spotifyCurrentPlaylistId,
    spotifyLogin,
    spotifyLogout,
    refreshSpotifyPlaylists,
    selectSpotifyPlaylist,
    spotifyQuickplay,
    spotifyDeletePlaylist,
    spotifyRemoveTrack,
    spotifyCreatePlaylist,
    spotifyAddCurrent,
    spotifyAddQueue,
    guildId,
    player,
  } = usePlayer();

  const [createName, setCreateName] = useState('');
  const [createPublic, setCreatePublic] = useState(true);
  const [loadingPlaylists, setLoadingPlaylists] = useState(false);

  const targetPlaylist = useMemo(() => {
    if (!spotifyCurrentPlaylistId) return null;
    return (
      spotifyPlaylists.find((p: SpotifyPlaylist) => String(p.id) === String(spotifyCurrentPlaylistId)) || {
        id: spotifyCurrentPlaylistId,
        name: 'Playlist',
      }
    );
  }, [spotifyPlaylists, spotifyCurrentPlaylistId]);

  const canAddTarget = !!(me && spotifyLinked && guildId && targetPlaylist?.id);

  const handleLoadPlaylists = async () => {
    setLoadingPlaylists(true);
    try {
      await refreshSpotifyPlaylists();
    } finally {
      setLoadingPlaylists(false);
    }
  };

  const handleCreate = async () => {
    const name = createName.trim() || 'Greg Playlist';
    await spotifyCreatePlaylist(name, createPublic);
    setCreateName('');
  };

  const handleQuickplay = (track: SpotifyTrack, e: React.MouseEvent) => {
    e.stopPropagation();

    const artistsStr = Array.isArray(track.artists)
      ? track.artists.map((a: any) => a?.name).filter(Boolean).join(', ')
      : String(track.artists || track.artist || '');

    spotifyQuickplay({
      name: track.name || track.title || '',
      artists: artistsStr,
      duration_ms: track.duration_ms ?? null,
      image: track.image || track.album?.images?.[0]?.url || null,
      uri: track.uri || null,
    });
  };

  const handleRemoveTrack = (track: SpotifyTrack, e: React.MouseEvent) => {
    e.stopPropagation();

    const uri = track.uri || (track.id ? `spotify:track:${track.id}` : '');
    if (!uri || !spotifyCurrentPlaylistId) return;
    if (!window.confirm(`Retirer "${track.name || track.title}" de la playlist ?`)) return;

    spotifyRemoveTrack(spotifyCurrentPlaylistId, uri);
  };

  const handleDeletePlaylist = (pl: SpotifyPlaylist, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Supprimer / unfollow "${pl.name}" ?`)) return;
    spotifyDeletePlaylist(pl.id);
  };

  if (!me) {
    return (
      <div className="card-greg p-3.5 h-full">
        <div className="text-sm text-muted">Connecte-toi a Discord pour lier Spotify</div>
      </div>
    );
  }

  return (
    <div className="card-greg p-3.5 flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex items-center justify-between gap-2.5 flex-shrink-0 flex-wrap">
        <div>
          <div className="text-sm text-muted">
            {spotifyLinked
              ? `Spotify lie : ${spotifyProfile?.display_name || spotifyProfile?.id || '-'}`
              : 'Spotify non lie'}
          </div>
          {spotifyLinked && spotifyProfile?.id && (
            <div className="text-xs text-muted/70 mt-0.5">@{spotifyProfile.id}</div>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          {!spotifyLinked ? (
            <button onClick={spotifyLogin} className="btn-ghost text-sm">
              Lier Spotify
            </button>
          ) : (
            <>
              <button onClick={spotifyLogout} className="btn-ghost text-sm">
                Delier
              </button>
              <button
                onClick={handleLoadPlaylists}
                className={`btn-ghost text-sm ${loadingPlaylists ? 'btn-loading' : ''}`}
                disabled={loadingPlaylists}
              >
                Charger playlists
              </button>
            </>
          )}
        </div>
      </div>

      {spotifyLinked && (
        <>
          <div className="flex items-center justify-between gap-2.5 mt-3 flex-wrap flex-shrink-0">
            <div className="flex items-center gap-1.5 px-3 py-2.5 rounded-[14px] border border-stroke bg-greg-dark min-w-[200px]">
              <span className="text-sm text-muted">Cible</span>
              <span className="font-black text-sm text-txt truncate">
                {targetPlaylist?.name || '-'}
              </span>
            </div>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => targetPlaylist?.id && spotifyAddCurrent(targetPlaylist.id)}
                disabled={!canAddTarget}
                className="btn-ghost text-xs"
              >
                + Titre en cours
              </button>
              <button
                onClick={() => {
                  if (!targetPlaylist?.id) return;
                  const n = Math.min(player.queue.length, 20);
                  if (!n) return;
                  if (!window.confirm(`Ajouter ${n} titre${n > 1 ? 's' : ''} a "${targetPlaylist.name}" ?`)) {
                    return;
                  }
                  spotifyAddQueue(targetPlaylist.id);
                }}
                disabled={!canAddTarget || !player.queue.length}
                className="btn-ghost text-xs"
              >
                + File
              </button>
            </div>
          </div>

          <div className="spotify-grid gap-3 mt-3 flex-1 min-h-0">
            <div className="rounded-[14px] border border-stroke/80 bg-greg-dark p-2.5 min-h-0 overflow-hidden flex flex-col">
              <div className="font-black text-sm mb-2 flex-shrink-0">Playlists</div>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5 pr-1 max-h-[44vh]">
                {spotifyPlaylists.length === 0 ? (
                  <div className="queue-empty text-xs">Aucune playlist chargee</div>
                ) : (
                  spotifyPlaylists.map((pl: SpotifyPlaylist) => {
                    const isActive = String(pl.id) === String(spotifyCurrentPlaylistId);
                    const img = pl.images?.[0]?.url || pl.image || pl.cover || '';
                    const owner =
                      typeof pl.owner === 'string'
                        ? pl.owner
                        : pl.owner?.display_name || pl.owner?.id || '';
                    const total = pl.tracks?.total ?? pl.tracks_total ?? pl.tracksCount ?? '';

                    return (
                      <div
                        key={pl.id}
                        className={`queue-item group ${isActive ? 'spotify-active' : ''}`}
                        onClick={() => selectSpotifyPlaylist(pl.id)}
                      >
                        {img && (
                          <div
                            className="queue-thumb"
                            style={{ backgroundImage: `url("${img}")` }}
                          />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-bold text-txt truncate">{pl.name}</div>
                          <div className="text-xs text-muted truncate">
                            {[owner, total ? `${total} tracks` : ''].filter(Boolean).join(' • ')}
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDeletePlaylist(pl, e)}
                          className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 w-[34px] h-[34px] rounded-[12px] border border-danger/30 bg-danger/10 hover:bg-danger/20 flex items-center justify-center text-txt"
                          title="Supprimer"
                        >
                          <Icon icon="trash" size={14} />
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <div className="rounded-[14px] border border-stroke/80 bg-greg-dark p-2.5 min-h-0 overflow-hidden flex flex-col">
              <div className="font-black text-sm mb-2 flex-shrink-0">Titres</div>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5 pr-1 max-h-[44vh]">
                {spotifyTracks.length === 0 ? (
                  <div className="queue-empty text-xs">Aucun titre charge</div>
                ) : (
                  spotifyTracks.map((track: SpotifyTrack, idx: number) => {
                    const name = track.name || track.title || 'Track';
                    const artist = Array.isArray(track.artists)
                      ? track.artists.map((a: any) => a?.name).filter(Boolean).join(', ')
                      : String(track.artists || track.artist || '');
                    const img = track.album?.images?.[0]?.url || track.image || '';

                    return (
                      <div key={`${track.id || idx}`} className="queue-item group">
                        {img && (
                          <div
                            className="queue-thumb"
                            style={{ backgroundImage: `url("${img}")` }}
                          />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-bold text-txt truncate">{name}</div>
                          <div className="text-xs text-muted truncate">{artist}</div>
                        </div>
                        <div className="flex gap-1 flex-shrink-0">
                          <button
                            onClick={(e) => handleQuickplay(track, e)}
                            className="opacity-0 group-hover:opacity-100 transition-opacity w-[34px] h-[34px] rounded-[12px] border border-stroke hover:border-primary/40 bg-white/5 hover:bg-primary/10 flex items-center justify-center text-txt"
                            title="Lire"
                          >
                            <Icon icon="play" size={14} />
                          </button>
                          <button
                            onClick={(e) => handleRemoveTrack(track, e)}
                            className="opacity-0 group-hover:opacity-100 transition-opacity w-[34px] h-[34px] rounded-[12px] border border-danger/30 bg-danger/10 hover:bg-danger/20 flex items-center justify-center text-txt"
                            title="Retirer"
                          >
                            <Icon icon="trash" size={14} />
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          <div className="flex gap-2.5 items-center flex-wrap mt-3 flex-shrink-0">
            <input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="Nom de playlist (ex: Greg Bangers)"
              className="flex-1 min-w-[200px] px-3 py-2.5 rounded-[12px] border border-stroke bg-[rgba(17,24,39,0.65)] text-txt outline-none text-sm"
            />
            <label className="flex items-center gap-2 text-xs text-muted select-none cursor-pointer">
              <input
                type="checkbox"
                checked={createPublic}
                onChange={(e) => setCreatePublic(e.target.checked)}
                className="accent-primary"
              />
              Publique
            </label>
            <button onClick={handleCreate} className="btn-primary text-sm">
              Creer playlist
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════
export default function Home() {
  const { me, guilds, guildId, socketReady, status, boot, setGuild, refreshMe } = usePlayer();

  const [booted, setBooted] = useState(false);
  const [quote, setQuote] = useState('Greg t observe avec un profond mepris.');

  useEffect(() => {
    setQuote(randomQuote());
  }, []);

  useEffect(() => {
    boot()
      .then(() => setBooted(true))
      .catch(() => setBooted(true));
  }, [boot]);

  useEffect(() => {
    const handler = async (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement)?.tagName?.toLowerCase();
      if (
        tag === 'input' ||
        tag === 'textarea' ||
        (ev.target as HTMLElement)?.isContentEditable
      ) {
        return;
      }

      const s = useStore.getState() as any;
      if (!s.me || !s.guildId) return;

      if (ev.code === 'Space') {
        ev.preventDefault();
        try {
          await api.togglePause(s.guildId, s.me.id);
        } catch {}
      } else if (ev.key?.toLowerCase() === 'n') {
        try {
          await api.queueSkip(s.guildId, s.me.id);
        } catch {}
      } else if (ev.key?.toLowerCase() === 'p') {
        try {
          await api.restart(s.guildId, s.me.id);
        } catch {}
      } else if (ev.key?.toLowerCase() === 'r') {
        try {
          await api.repeat(s.guildId, s.me.id);
        } catch {}
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    const handler = () => {
      refreshMe().catch(() => {});
    };

    window.addEventListener('focus', handler);
    return () => window.removeEventListener('focus', handler);
  }, [refreshMe]);

  const avatarUrl = discordAvatarUrl(me, 128);
  const userName = me?.global_name || me?.display_name || me?.username || '';

  return (
    <div
      className="flex flex-col h-[100dvh]"
      style={{
        padding: `calc(16px + env(safe-area-inset-top, 0px)) calc(16px + env(safe-area-inset-right, 0px)) calc(16px + env(safe-area-inset-bottom, 0px)) calc(16px + env(safe-area-inset-left, 0px))`,
        gap: '14px',
      }}
    >
      <header className="flex items-start justify-between gap-3.5 flex-shrink-0 flex-wrap min-[1100px]:flex-nowrap">
        <div className="card-greg-light flex items-center gap-2.5 px-3.5 py-3 min-w-[240px]">
          <img
            src="/images/icon.png"
            alt="Greg"
            className="w-9 h-9 rounded-[10px] object-cover border border-stroke bg-[#111827]"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
          <div>
            <div className="font-black tracking-wide text-sm">Greg le Consanguin</div>
            <div className="text-xs text-muted mt-0.5">Web Player</div>
          </div>
        </div>

        <SearchBar />

        <div className="flex gap-2.5 flex-wrap min-[1100px]:flex-nowrap min-w-[260px]">
          <div className="card-greg-light flex items-center gap-2.5 px-3.5 py-2.5 min-w-0">
            <div
              className="w-[34px] h-[34px] rounded-[12px] flex items-center justify-center font-black flex-shrink-0"
              style={{
                background: avatarUrl
                  ? `url("${avatarUrl}") center/contain no-repeat rgba(15,23,42,0.65)`
                  : 'rgba(99,102,241,0.18)',
                border: '1px solid rgba(99,102,241,0.25)',
                color: avatarUrl ? 'transparent' : undefined,
              }}
            >
              {!avatarUrl && (userName?.[0]?.toUpperCase() || '?')}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-bold text-sm truncate">{userName || 'Non connecte'}</div>
              <div className="text-xs text-muted mt-0.5">{me ? 'Connecte' : 'Discord'}</div>
            </div>
            {me ? (
              <button
                onClick={async () => {
                  try {
                    await api.logout();
                    useStore.getState().setMe(null);
                    useStore.getState().setGuilds([]);
                    useStore.getState().setGuildId('');
                    useStore.getState().setSpotifyLinked(false);
                    useStore.getState().setSpotifyProfile(null);
                    useStore.getState().setSpotifyPlaylists([]);
                    useStore.getState().setSpotifyTracks([]);
                    localStorage.removeItem('greg.webplayer.guild_id');
                    localStorage.removeItem('greg.spotify.last_playlist_id');
                    window.location.reload();
                  } catch {}
                }}
                className="btn-ghost text-xs flex-shrink-0"
              >
                Deco
              </button>
            ) : (
              <a href={api.getLoginUrl()} className="btn-ghost text-xs flex-shrink-0">
                Se connecter
              </a>
            )}
          </div>

          <div className="card-greg-light flex items-center gap-2.5 px-3 py-2.5 min-w-0">
            <label className="text-xs text-muted flex-shrink-0">Serveur</label>
            <select
              value={guildId}
              onChange={(e) => setGuild(e.target.value)}
              className="flex-1 px-2.5 py-2 rounded-[10px] border border-stroke bg-[rgba(17,24,39,0.65)] text-txt outline-none text-sm min-w-0"
            >
              <option value="">- Choisir -</option>
              {guilds.map((g: any) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      <main className="flex-1 min-h-0 main-grid gap-3.5">
        <div className="min-h-0 max-[1100px]:order-1 max-[1100px]:h-auto">
          <Queue />
        </div>
        <div className="min-h-0 max-[1100px]:order-0 max-[1100px]:h-auto">
          <NowPlaying />
        </div>
        <div className="min-h-0 max-[1100px]:order-2 max-[1100px]:h-auto">
          <SpotifyPanel />
        </div>
      </main>

      <footer className="flex-shrink-0">
        <div
          className={`rounded-greg px-3.5 py-3 shadow-greg text-[13px] transition-all duration-300 ${
            status.kind === 'ok'
              ? 'status-ok'
              : status.kind === 'err'
                ? 'status-err'
                : 'border border-stroke bg-greg-darker'
          }`}
          style={{
            color:
              status.kind === 'err'
                ? 'rgba(254,226,226,0.95)'
                : 'rgba(226,232,240,0.95)',
          }}
        >
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full flex-shrink-0 ${
                socketReady ? 'bg-ok animate-pulse-glow' : 'bg-danger'
              }`}
            />
            <span>{status.text}</span>
            {!booted && <span className="text-xs text-muted">(initialisation)</span>}
          </div>
        </div>
      </footer>
    </div>
  );
}