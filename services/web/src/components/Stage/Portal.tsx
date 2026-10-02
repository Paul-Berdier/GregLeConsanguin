'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { YT_API_FAILED, useYouTubePlayer } from '@/hooks/useYouTubePlayer';
import type { YTPlayer } from '@/hooks/useYouTubePlayer';
import { extractVideoId } from '@/lib/format';
import { COVERED, YT_STATE, coverNext, coverVisible, isPlaceholderThumb, loadStart, posterUrl, revealIn, rewound } from '@/lib/stage/cover';
import type { Cover, CoverEvent } from '@/lib/stage/cover';
import { CTL_INIT, CTL_TICK_MS, afterDecision, decide, gateLoad, nextHold, rateCheck } from '@/lib/sync/controller';
import type { CtlState } from '@/lib/sync/controller';
import { refClock, serverNow } from '@/lib/sync/live';
import type { ClockView } from '@/lib/sync/refclock';
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

/** Cible de la vidéo (s) : la position du son selon l'horloge de référence (refclock), plus le réglage. null : aucun son. */
function targetPos(offset: number): number | null {
  const ms = refClock.positionAt(serverNow(performance.now()));
  return ms == null ? null : Math.max(0, ms / 1000 + offset);
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
  const clock = useStore((s) => s.clock);   // horloge de référence : play_id, statut, lien du titre joué
  const still = paused || clock.status === 'stalled';   // pause, ou flux du bot bloqué : la vidéo attend
  const crownRef = useRef(crown);
  crownRef.current = crown;
  const stillRef = useRef(still);
  stillRef.current = still;
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const videoRef = useRef(videoId);
  videoRef.current = videoId;
  const playerRef = useRef<YTPlayer | null>(null);
  const ytState = useRef<number>(YT_STATE.UNSTARTED);
  const loaded = useRef<{ id: string | null; playId: string | null }>({ id: null, playId: null });   // vidéo chargée, pour quel play_id
  const awaiting = useRef(false);   // titre choisi, le bot ne le joue pas encore : vidéo arrêtée sous le poster
  const ctl = useRef<CtlState>(CTL_INIT);
  const hold = useRef(0);           // pas de correction avant (performance.now)
  const rateOk = useRef(true);      // YouTube applique les vitesses demandées (sinon : sauts seuls)
  const asked = useRef<{ rate: number; at: number } | null>(null);   // vitesse demandée, à confirmer

  const dispatch = useCallback((ev: CoverEvent) => setCover((c) => coverNext(c, ev)), []);

  const player = useYouTubePlayer(wrapRef, {
    onState: (s) => {
      ytState.current = s;
      dispatch({ type: 'yt', state: s, now: performance.now() });
      // l'iframe ne suit que le son : relancée si elle s'arrête seule, arrêtée si elle part pendant la pause ou un
      // blocage ; rien tant que le bot n'a pas commencé ce titre
      if (awaiting.current) return;
      if (s === YT_STATE.PAUSED && !stillRef.current) playerRef.current?.playVideo();
      if (s === YT_STATE.PLAYING && stillRef.current) playerRef.current?.pauseVideo();
    },
    onError: (code) => { if (code === YT_API_FAILED) setNoApi(true); else setUnavailable(true); dispatch({ type: 'error' }); },
  }, !!(videoId || nextId));   // créé au premier titre qui peut jouer (déconnecté, rien en file : aucun lecteur)
  playerRef.current = player;
  // l'API a fini par se charger (nouvel essai, réseau revenu) : la note « vidéo indisponible » part
  useEffect(() => { if (player) setNoApi(false); }, [player]);

  /**
   * Charge la vidéo sous le poster, à la position du son si l'horloge décrit cette vidéo (sinon au début : ancien bot,
   * saut optimiste, l'ancien titre joue encore). Régulateur neuf : loadVideoById remet la vitesse à 1, le régulateur
   * la réappliquera ; les vitesses sont retentées à chaque vidéo (un direct les refuse, pas la suivante).
   */
  const load = useCallback((p: YTPlayer, id: string, playId: string | null) => {
    loaded.current = { id, playId };
    awaiting.current = false;
    ctl.current = CTL_INIT;
    rateOk.current = true;
    asked.current = null;
    const here = extractVideoId(useStore.getState().clock.url) === id;
    try { p.loadVideoById({ videoId: id, startSeconds: loadStart(here ? targetPos(0) ?? 0 : 0, offsetRef.current) }); } catch {}
  }, []);

  // Changement de titre : le poster couvre tout de suite, la vidéo précédente s'arrête dessous.
  useEffect(() => {
    setUnavailable(false);
    dispatch({ type: videoId ? 'track' : 'stop' });
    loaded.current = { id: null, playId: null };
    awaiting.current = !!videoId;
    if (!player) return;
    try { player.stopVideo(); } catch {}
  }, [videoId, player, dispatch]);

  // Démarrage gardé (gateLoad) : la vidéo part quand le bot joue vraiment ce titre (statut playing, nouveau play_id) ;
  // un ancien bot (sans clock) : tout de suite, comme avant. Le bot recharge la même vidéo (« Depuis le début »,
  // boucle, reprise après coupure) : elle attend sous le poster. Les ids comptent, pas les liens : le bot garde le
  // lien tel que donné, la même vidéo peut revenir sous un autre (youtu.be/X?si=… puis watch?v=X).
  useEffect(() => {
    if (!player || !videoId) return;
    if (!clock.compat && clock.status === 'loading' && loaded.current.id === videoId && !awaiting.current) {
      awaiting.current = true;
      dispatch({ type: 'track' });
      try { player.stopVideo(); } catch {}
      return;
    }
    if (!gateLoad(clock, extractVideoId(clock.url), videoId, loaded.current)) return;
    if (loaded.current.id === videoId) dispatch({ type: 'track' });   // même vidéo, nouvelle lecture
    load(player, videoId, clock.playId);
  }, [videoId, player, clock, dispatch, load]);

  // Ancien bot (sans clock) : le son recule sur la même vidéo → rechargée sous le poster (tech.md §5.4). Avec clock,
  // le nouveau play_id s'en charge (démarrage gardé). videoRef tient encore l'id rendu.
  useEffect(() => useStore.subscribe((s, prev) => {
    const p = playerRef.current, id = videoRef.current;
    if (!s.clock.compat || !p || !id || s.tickBase === prev.tickBase || extractVideoId(s.player.current?.url) !== id) return;
    if (!rewound(prev.tickBase, prev.player.paused, s.tickBase)) return;
    dispatch({ type: 'track' });
    try { p.loadVideoById({ videoId: id, startSeconds: loadStart(s.tickBase.pos, offsetRef.current) }); } catch {}
  }), [dispatch]);

  // Pause, ou flux du bot bloqué : la vidéo attend sous le poster, puis repart avec le son.
  useEffect(() => {
    if (!player || !videoId || awaiting.current) return;
    try { if (still) player.pauseVideo(); else player.playVideo(); } catch {}
    if (still) dispatch({ type: 'pause' });
  }, [still, player, videoId, dispatch]);

  // Armé : révélation à armedAt + REVEAL_AFTER_PLAYING_MS ; un calage (BUFFERING puis PLAYING) change `cover` et relance
  // l'effet sans la repousser.
  useEffect(() => {
    if (cover.phase !== 'armed') return;
    const reveal = setTimeout(() => dispatch({ type: 'reveal', now: performance.now() }), revealIn(cover, performance.now()));
    return () => clearTimeout(reveal);
  }, [cover, dispatch]);   // coverNext rend le même objet tant que rien ne change

  // Attente après une reprise, un blocage ou un nouveau play_id : le client Discord se recale (nextHold).
  const prevClock = useRef<ClockView | null>(null);
  useEffect(() => {
    hold.current = nextHold(prevClock.current, clock, performance.now(), hold.current);
    prevClock.current = clock;
  }, [clock]);

  // Régulateur à 4 Hz tant que YouTube joue et que l'onglet est visible (decide) : vitesse ×0,90 à ×1,10, ou saut au-delà
  // de 2 s (le poster revient le temps que l'habillage YouTube parte). Le réglage « Synchro vidéo » passe par lui aussi.
  useEffect(() => {
    if (!player || !videoId || still) return;
    const tick = (): void => {
      if (awaiting.current || document.visibilityState !== 'visible' || ytState.current !== YT_STATE.PLAYING) return;
      // l'horloge décrit une autre vidéo (ancien bot après un saut optimiste, état du nouveau titre pas encore reçu)
      if (extractVideoId(useStore.getState().clock.url) !== videoId) return;
      const now = performance.now();
      let reported: number | undefined;
      try { reported = player.getPlaybackRate(); } catch {}
      const check = rateCheck(asked.current, reported, now);
      if (check !== 'wait') asked.current = null;
      if (check === 'failed') rateOk.current = false;   // vitesse non confirmée : sauts seuls
      const target = targetPos(offsetRef.current);
      if (target == null) return;
      const d = decide({ target, current: player.getCurrentTime(), state: ctl.current, rateOk: rateOk.current,
        holdUntil: hold.current, now, compat: useStore.getState().clock.compat });
      if (!d) return;
      if ('seek' in d) {
        try { player.seekTo(d.seek, true); } catch {}
        dispatch({ type: 'seek', now });
      } else {
        try { player.setPlaybackRate(d.rate); } catch {}
        asked.current = { rate: d.rate, at: now };
      }
      ctl.current = afterDecision(ctl.current, d, now);
    };
    const id = setInterval(tick, CTL_TICK_MS);
    // retour sur l'onglet : recalage tout de suite, sans attente
    const back = (): void => { if (document.visibilityState === 'visible') { hold.current = 0; tick(); } };
    document.addEventListener('visibilitychange', back);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', back); };
  }, [player, videoId, still, dispatch]);

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
        <div className="posters" data-covered={coverVisible(cover, still)}>
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
