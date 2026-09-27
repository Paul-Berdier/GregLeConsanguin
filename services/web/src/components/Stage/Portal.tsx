'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { YT_API_FAILED, useYouTubePlayer } from '@/hooks/useYouTubePlayer';
import type { YTPlayer } from '@/hooks/useYouTubePlayer';
import { extractVideoId } from '@/lib/format';
import { livePosition } from '@/lib/playerUtils';
import {
  ALIGN_AFTER_PLAYING_MS, ALIGN_THRESHOLD_S, COVERED, DRIFT_CHECK_MS, MIN_SEEK_GAP_MS, RUN_THRESHOLD_S, YT_STATE,
  alignDue, coverNext, coverVisible, driftSeek, isPlaceholderThumb, loadStart, posterUrl, revealIn, rewound,
} from '@/lib/stage/cover';
import type { Cover, CoverEvent } from '@/lib/stage/cover';
import type { CrownMode } from '@/lib/stage/coronation';
import { t } from '@/theme/copy';
import type { Ceremony } from './coronation';

export type PortalProps = {
  videoId: string | null;   // titre en cours (null : rien, le portail s'efface la nuit)
  nextId: string | null;    // prochain titre : son poster est décodé d'avance
  paused: boolean;
  offset: number;           // décalage vidéo ↔ son (s), useVideoOffset
  art: string | null;       // pochette d'un titre sans vidéo YouTube (SoundCloud) : image fixe, comme l'ancien lecteur
  crown: Ceremony | null;   // cérémonie du titre en cours (coronation.ts) : le relais des posters suit son plan
};
/** Un poster à l'écran ; mode et ms : le Couronnement qui l'a amené (ms : durée de son fondu d'entrée, null : --dur-reveal). */
type PosterEntry = { id: string; leaving: boolean; mode: CrownMode | null; ms: number | null };

/** Vidéos sans maxresdefault (vu au préchargement) : leur poster part directement en hqdefault. */
const noMaxres = new Set<string>();
/** Poster du prochain titre, déjà décodé (id → url) : le fantôme du vol le porte, net à l'arrivée (coronation.ts). */
export const decodedPosters = new Map<string, string>();
/** Les images décodées elles-mêmes, gardées jusqu'à leur éviction : l'image reste en mémoire pour le vol, pas seulement son url. */
const decodedImages = new Map<string, HTMLImageElement>();
const DECODED_MAX = 8;

/** Position du son (s) d'après le store, comme l'horloge. */
function clockPos(): number {
  const s = useStore.getState();
  return livePosition(s.tickBase, s.player.paused, performance.now());
}

/**
 * Poster maxresdefault, repli hqdefault (404 ou vignette grise 120 × 90). Visible une fois chargé.
 * held : retenu sous le fantôme jusqu'à l'atterrissage ; cut : arrivé en vol, il paraît sans fondu (le fantôme le couvre).
 */
function Poster({ id, leaving, held, cut, ms }: { id: string; leaving: boolean; held: boolean; cut: boolean; ms: number | null }) {
  const hq = posterUrl(id, 'hq');
  const [src, setSrc] = useState(() => (noMaxres.has(id) ? hq : posterUrl(id)));
  const [ready, setReady] = useState(false);
  const fallBack = () => { noMaxres.add(id); setSrc(hq); };
  return (
    <img className="poster" src={src} alt="" decoding="async" draggable={false}
      data-ready={ready} data-leaving={leaving || undefined}
      data-held={held || undefined} data-cut={cut || undefined}
      style={ms ? ({ '--poster-ms': `${ms}ms` } as CSSProperties) : undefined}
      onLoad={(e) => { if (src !== hq && isPlaceholderThumb(e.currentTarget.naturalWidth)) fallBack(); else setReady(true); }}
      onError={() => { if (src !== hq) fallBack(); }}/>
  );
}

/**
 * Le portail de pierre (9 tranches, rendu Blender) et la vidéo : lecteur YouTube persistant sous un poster
 * qui le couvre jusqu'à PLAYING + REVEAL_AFTER_PLAYING_MS et pendant la pause (tech.md §5.3). Styles : portal.css.
 * Au Couronnement (coronation.ts) : en vol, le nouveau poster attend l'atterrissage sous le fantôme et l'ancien
 * part en scale(1.03) ; sinon, le nouveau entre en fondu (--poster-ms du plan).
 */
export default function Portal({ videoId, nextId, paused, offset, art, crown }: PortalProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [cover, setCover] = useState<Cover>(COVERED);
  const [unavailable, setUnavailable] = useState(false);   // cette vidéo refuse l'intégration (remis à chaque titre)
  const [noApi, setNoApi] = useState(false);               // l'API YouTube n'a pas pu se charger : aucun lecteur ici
  const [posters, setPosters] = useState<PosterEntry[]>([]);
  const crownRef = useRef(crown);
  crownRef.current = crown;
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const videoRef = useRef(videoId);
  videoRef.current = videoId;
  const playerRef = useRef<YTPlayer | null>(null);
  const ytState = useRef<number>(YT_STATE.UNSTARTED);
  const lastSeek = useRef(-Infinity);   // aucun saut encore : pas 0, qui muselait la dérive 15 s après le chargement

  const dispatch = useCallback((ev: CoverEvent) => setCover((c) => coverNext(c, ev)), []);
  /** Saut réel seulement : sans lecteur (décalage relu au montage), rien n'est noté, la dérive n'est pas muselée 15 s. */
  const seek = useCallback((to: number) => {
    const p = playerRef.current;
    if (!p) return;
    try { p.seekTo(to, true); lastSeek.current = performance.now(); } catch {}
  }, []);
  /** Saut de correction : YouTube remontre son habillage, le poster revient le temps qu'il parte. */
  const correct = useCallback((threshold: number) => {
    const p = playerRef.current;
    if (!p) return;
    const to = driftSeek(p.getCurrentTime(), clockPos(), offsetRef.current, threshold);
    if (to == null) return;
    seek(to);
    dispatch({ type: 'seek', now: performance.now() });
  }, [dispatch, seek]);

  const player = useYouTubePlayer(wrapRef, {
    onState: (s) => {
      ytState.current = s;
      dispatch({ type: 'yt', state: s, now: performance.now() });
      // l'iframe ne suit que le son : relancée si elle s'arrête seule, arrêtée si elle part pendant la pause
      if (s === YT_STATE.PAUSED && !pausedRef.current) playerRef.current?.playVideo();
      if (s === YT_STATE.PLAYING && pausedRef.current) playerRef.current?.pauseVideo();
    },
    onError: (code) => { if (code === YT_API_FAILED) setNoApi(true); else setUnavailable(true); dispatch({ type: 'error' }); },
  });
  playerRef.current = player;

  // Changement de titre : le poster couvre, puis loadVideoById dans la même iframe.
  useEffect(() => {
    setUnavailable(false);
    dispatch({ type: videoId ? 'track' : 'stop' });
    if (!player) return;
    try {
      if (videoId) player.loadVideoById({ videoId, startSeconds: loadStart(clockPos(), offsetRef.current) });
      else player.stopVideo();
    } catch {}
  }, [videoId, player, dispatch]);

  // Le son recule sur la même vidéo (« Reprendre au début », boucle, même titre deux fois de suite) : la vidéo
  // est rechargée sous le poster (tech.md §5.4). Les ids comptent, pas les liens : le bot garde le lien tel que
  // donné, la même vidéo peut revenir sous un autre (youtu.be/X?si=… puis watch?v=X). videoRef tient encore l'id
  // rendu : une autre vidéo passe par l'effet ci-dessus.
  useEffect(() => useStore.subscribe((s, prev) => {
    const p = playerRef.current, id = videoRef.current;
    if (!p || !id || s.tickBase === prev.tickBase || extractVideoId(s.player.current?.url) !== id) return;
    if (!rewound(prev.tickBase, prev.player.paused, s.tickBase)) return;
    dispatch({ type: 'track' });
    try { p.loadVideoById({ videoId: id, startSeconds: loadStart(s.tickBase.pos, offsetRef.current) }); } catch {}
  }), [dispatch]);

  // Pause et reprise suivent le son ; le poster revient pendant la pause.
  useEffect(() => {
    if (!player || !videoId) return;
    try { if (paused) player.pauseVideo(); else player.playVideo(); } catch {}
    if (paused) dispatch({ type: 'pause' });
  }, [paused, player, videoId, dispatch]);

  // Armé : alignement une fois à armedAt + 1,2 s (encore caché), révélation à armedAt + REVEAL_AFTER_PLAYING_MS.
  // Les deux échéances partent de l'armement : un calage (BUFFERING puis PLAYING) change `cover` et relance l'effet
  // sans les repousser.
  const alignedFor = useRef<number | null>(null);   // armedAt du dernier alignement fait
  useEffect(() => {
    if (cover.phase !== 'armed') return;
    const now = performance.now();
    const reveal = setTimeout(() => dispatch({ type: 'reveal', now: performance.now() }), revealIn(cover, now));
    const align = alignDue(cover) && alignedFor.current !== cover.armedAt
      ? setTimeout(() => { alignedFor.current = cover.armedAt; correct(ALIGN_THRESHOLD_S); },
        Math.max(0, cover.armedAt + ALIGN_AFTER_PLAYING_MS - now))
      : undefined;
    return () => { clearTimeout(reveal); clearTimeout(align); };
  }, [cover, correct, dispatch]);   // coverNext rend le même objet tant que rien ne change

  // Révélé : dérive vérifiée toutes les 4 s (onglet visible, pas en BUFFERING, pas de saut depuis 15 s).
  useEffect(() => {
    if (cover.phase !== 'revealed' || paused) return;
    const check = () => {
      if (document.visibilityState !== 'visible' || ytState.current === YT_STATE.BUFFERING) return;
      if (performance.now() - lastSeek.current < MIN_SEEK_GAP_MS) return;
      correct(RUN_THRESHOLD_S);
    };
    const id = setInterval(check, DRIFT_CHECK_MS);
    document.addEventListener('visibilitychange', check);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', check); };
  }, [cover.phase, paused, correct]);

  // Réglage du décalage : la vidéo saute tout de suite à la nouvelle position, sans poster (on la regarde).
  const firstOffset = useRef(true);
  useEffect(() => {
    if (firstOffset.current) { firstOffset.current = false; return; }
    if (videoRef.current) seek(Math.max(0, clockPos() + offset));
  }, [offset, seek]);

  // Posters : le nouveau s'allume une fois chargé, l'ancien s'efface en 200 ms. La cérémonie est lue ici, avant
  // setPosters (dont la fonction tourne au rendu suivant, quand crownRef a pu changer).
  useEffect(() => {
    const cr = crownRef.current;
    const mode = cr?.mode ?? null, ms = cr?.plan.posterMs || null;
    setPosters((list) => {
      const old = list.filter((p) => p.id !== videoId).map((p) => ({ ...p, leaving: true }));
      return videoId ? [...old, { id: videoId, leaving: false, mode, ms }] : old;
    });
    const tm = setTimeout(() => setPosters((list) => list.filter((p) => !p.leaving)), 260);
    return () => clearTimeout(tm);
  }, [videoId]);

  // Poster du prochain titre préchargé et décodé (motion.md P7 : décoder avant d'échanger) ; retenu pour le vol.
  useEffect(() => {
    if (!nextId || decodedPosters.has(nextId)) return;
    const load = (hq: boolean): void => {
      const im = new Image();
      im.decoding = 'async';
      im.src = posterUrl(nextId, hq ? 'hq' : 'maxres');
      const fallBack = (): void => { if (!hq) { noMaxres.add(nextId); load(true); } };
      im.decode().then(() => {
        if (!hq && isPlaceholderThumb(im.naturalWidth)) { fallBack(); return; }
        decodedPosters.set(nextId, im.src);
        decodedImages.set(nextId, im);
        if (decodedPosters.size > DECODED_MAX) {
          const old = decodedPosters.keys().next().value as string;
          decodedPosters.delete(old); decodedImages.delete(old);
        }
      }, fallBack);
    };
    load(noMaxres.has(nextId));
  }, [nextId]);

  const flying = crown?.mode === 'flight' && !crown.landed;
  return (
    <div className="portal">
      <div className="video">
        <div className="yt" ref={wrapRef} aria-hidden="true"/>
        <div className="posters" data-covered={coverVisible(cover, paused)}>
          {posters.map((p) => <Poster key={p.id} id={p.id} leaving={p.leaving} held={!p.leaving && p.mode === 'flight' && flying}
            cut={p.mode === 'flight'} ms={p.ms}/>)}
          {!videoId && art && <img className="poster art" src={art} alt="" decoding="async" draggable={false} data-ready="true"/>}
        </div>
        <div className="veil"/>
        <div className="paused-badge plaque" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6.5" y="5" width="4" height="14"/><rect x="13.5" y="5" width="4" height="14"/></svg>
          {t('now.state.paused')}
        </div>
        {(unavailable || (noApi && videoId)) && <p className="video-note plaque">{t('now.videoUnavailable')}</p>}
      </div>
    </div>
  );
}
