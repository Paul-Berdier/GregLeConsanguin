'use client';

// Provisoire : remplacé par la scène (portail, rosace) à l'étape 2.

import { useState, useEffect, useRef } from 'react';
import { usePlayer, useStore } from '@/hooks/usePlayer';
import { useProgress } from '@/hooks/useProgress';
import { extractVideoId } from '@/lib/format';
import { Ic } from '@/components/icons';

// ═══════════════════════════════
// Video Player (YouTube embed)
// ═══════════════════════════════
export default function VideoPlayer() {
  const { player, togglePause, skip, stop, toggleRepeat, restartTrack } = usePlayer();
  const { progressRef, currentRef, totalRef } = useProgress();
  const cur = player.current;
  const videoId = extractVideoId(cur?.url);

  // YouTube IFrame API
  const containerRef = useRef<HTMLDivElement>(null);
  const ytPlayerRef = useRef<any>(null);
  const prevVideoId = useRef<string | null>(null);
  const [syncOffset, setSyncOffset] = useState(0); // seconds, user-adjustable
  const [showSync, setShowSync] = useState(false);

  // Load YouTube IFrame API once
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if ((window as any).YT?.Player) return;
    if (document.querySelector('script[src*="youtube.com/iframe_api"]')) return;
    const tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
  }, []);

  // Create/update player when videoId changes
  useEffect(() => {
    if (!videoId || !containerRef.current) {
      // Destroy player if no video
      if (ytPlayerRef.current) {
        try { ytPlayerRef.current.destroy(); } catch {}
        ytPlayerRef.current = null;
      }
      prevVideoId.current = null;
      return;
    }

    if (videoId === prevVideoId.current && ytPlayerRef.current) return;
    prevVideoId.current = videoId;

    const create = () => {
      if (!containerRef.current) return;
      // Clear container
      containerRef.current.innerHTML = '<div id="yt-embed"></div>';

      try {
        ytPlayerRef.current = new (window as any).YT.Player('yt-embed', {
          videoId,
          playerVars: {
            autoplay: 1, mute: 1, controls: 0, showinfo: 0, rel: 0,
            modestbranding: 1, iv_load_policy: 3, disablekb: 1,
            playsinline: 1, fs: 0, cc_load_policy: 0,
          },
          events: {
            onReady: (e: any) => {
              e.target.mute();
              e.target.playVideo();
            },
            onStateChange: (e: any) => {
              // Prevent user from pausing the video — force play
              // YT.PlayerState.PAUSED = 2
              if (e.data === 2) {
                const s = useStore.getState();
                if (!s.player.paused) {
                  // Audio is still playing, force video to play too
                  e.target.playVideo();
                }
              }
            },
          },
        });
      } catch (err) {
        console.warn('YT Player create failed:', err);
      }
    };

    if ((window as any).YT?.Player) {
      create();
    } else {
      (window as any).onYouTubeIframeAPIReady = create;
    }
  }, [videoId]);

  // Sync video playback state with audio (pause/resume)
  useEffect(() => {
    const yt = ytPlayerRef.current;
    if (!yt || !videoId) return;
    try {
      if (player.paused) {
        yt.pauseVideo?.();
      } else {
        yt.playVideo?.();
      }
    } catch {}
  }, [player.paused, videoId]);

  // Apply sync offset when it changes
  useEffect(() => {
    const yt = ytPlayerRef.current;
    if (!yt || !videoId) return;
    try {
      const s = useStore.getState();
      const pos = s.tickBase.pos + syncOffset;
      if (pos >= 0 && yt.seekTo) {
        yt.seekTo(pos, true);
      }
    } catch {}
  }, [syncOffset, videoId]);

  return (
    <div className="flex flex-col gap-4 min-h-0 flex-1">
      {/* Video / Artwork area */}
      <div className="video-frame">
        {videoId ? (
          <>
            {/* YouTube player container — pointer-events:none prevents user interaction */}
            <div ref={containerRef} className="absolute inset-0 z-[1]"
              style={{ pointerEvents: 'none' }}>
              <div id="yt-embed" className="w-full h-full"/>
            </div>
            {/* Invisible overlay to block all clicks on the video */}
            <div className="absolute inset-0 z-[3]" style={{ pointerEvents: 'auto', cursor: 'default' }}
              onClick={e => e.preventDefault()}/>
          </>
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

        {/* Overlay: track info at bottom */}
        {cur && (
          <div className="absolute bottom-0 left-0 right-0 z-10 p-4 pb-3" style={{ pointerEvents: 'none' }}>
            <div className="flex items-end gap-3">
              <div className="flex-1 min-w-0">
                {!player.paused && (
                  <div className="wave-bars mb-2">
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
                <div className="flex items-center gap-2" style={{ pointerEvents: 'auto' }}>
                  <button onClick={() => setShowSync(v => !v)}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white/10 backdrop-blur-sm text-xs text-white/70 hover:bg-white/20 transition-colors cursor-pointer border-none"
                    title="Synchroniser la vidéo">
                    <Ic icon="video" size={14}/>
                    {syncOffset !== 0 ? `${syncOffset > 0 ? '+' : ''}${syncOffset.toFixed(1)}s` : 'Sync'}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Sync slider overlay */}
        {showSync && videoId && (
          <div className="absolute top-3 left-3 right-3 z-20 animate-fade-up" style={{ pointerEvents: 'auto' }}>
            <div className="glass-subtle p-3 flex items-center gap-3">
              <span className="text-xs text-txt-muted whitespace-nowrap">Décalage vidéo</span>
              <input type="range" min="-10" max="10" step="0.5"
                value={syncOffset}
                onChange={e => {
                  const val = parseFloat(e.target.value);
                  setSyncOffset(val);
                  // Seek the YT player to current audio position + offset
                  const yt = ytPlayerRef.current;
                  if (yt?.seekTo) {
                    const s = useStore.getState();
                    const now = performance.now();
                    const elapsed = s.player.paused ? 0 : (now - s.tickBase.at) / 1000;
                    const audioPos = s.tickBase.pos + elapsed + val;
                    yt.seekTo(Math.max(0, audioPos), true);
                  }
                }}
                className="flex-1 accent-accent h-1.5 cursor-pointer"/>
              <span className="text-xs font-mono text-accent min-w-[40px] text-right">
                {syncOffset > 0 ? '+' : ''}{syncOffset.toFixed(1)}s
              </span>
              <button onClick={() => { setSyncOffset(0); setShowSync(false);
                const yt = ytPlayerRef.current;
                if (yt?.seekTo) { const s = useStore.getState(); const now = performance.now(); const elapsed = s.player.paused ? 0 : (now - s.tickBase.at) / 1000; yt.seekTo(Math.max(0, s.tickBase.pos + elapsed), true); }
              }}
                className="text-xs text-txt-muted hover:text-white transition-colors cursor-pointer bg-transparent border-none">
                ✕
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Progress */}
      <div className="px-1">
        <div className="progress-track">
          <div ref={progressRef} className="progress-fill" style={{ width: '0%' }}/>
        </div>
        <div className="flex justify-between mt-1 text-xs text-txt-muted font-mono">
          <span ref={currentRef}>0:00</span>
          <span ref={totalRef}>--:--</span>
        </div>
      </div>

      {/* Controls */}
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
