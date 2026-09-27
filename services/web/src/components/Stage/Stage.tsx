'use client';

import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, RefObject } from 'react';
import { useStore } from '@/hooks/usePlayer';
import { useStageLayout } from '@/hooks/useStageLayout';
import { useStageClock } from '@/hooks/useStageClock';
import { useVideoOffset } from '@/hooks/useVideoOffset';
import { extractVideoId } from '@/lib/format';
import { fitNight, nightBottom, sameLayout, stageCssVars } from '@/lib/stage/layout';
import type { StageLayout } from '@/lib/stage/layout';
import { dialGeometry, paneMask } from '@/lib/stage/dial';
import { stageScene } from '@/lib/stage/scene';
import type { Scene } from '@/lib/stage/scene';
import { t } from '@/theme/copy';
import Rose from './Rose';
import Clock, { TimesRow } from './Clock';
import NightState from './NightState';
import Portal from './Portal';
import SyncOffset from './SyncOffset';
import NowPlaying, { NOW_TITLE_ID } from './NowPlaying';
import Transport from './Transport';

type NightFit = { layout: StageLayout; bottom: number };

/**
 * Mise en page de la nuit (fitNight, layout.ts), remesurée quand la colonne, le bloc du dessous ou le texte de
 * la nuit changent de taille (fenêtre, police chargée, une ligne de plus). null le jour : useStageLayout suffit.
 * Écart 10 du plan de l'étape 2 : quand le texte de nuit ne tient pas sous la rose du jour (1280 × 720 :
 * R 280 → 244 ; 1366 × 657 : 242 → 205), la rose change de taille d'un coup en passant jour ↔ nuit, pendant
 * le fondu de la rosace ; l'étape 4 l'animera (FLIP en transform sur la rose).
 */
function useNightFit(scene: Scene, colRef: RefObject<HTMLElement>, stageRef: RefObject<HTMLElement>,
  belowRef: RefObject<HTMLElement>): NightFit | null {
  const [fit, setFit] = useState<NightFit | null>(null);

  useLayoutEffect(() => {
    const col = colRef.current, below = belowRef.current;
    const inner = stageRef.current?.querySelector<HTMLElement>('.night .vl-inner');
    const heart = inner?.querySelector<HTMLElement>('.heart');
    if (scene === 'day' || !col || !below || !inner || !heart) { setFit(null); return; }
    const measure = () => {
      // le texte sous l'oculus : sa hauteur ne dépend pas de R (celles de l'oculus et de sa marge, si)
      const tail = inner.offsetHeight - heart.offsetHeight - parseFloat(getComputedStyle(heart).marginBottom);
      const layout = fitNight({ colW: col.clientWidth, colH: col.clientHeight, belowH: below.offsetHeight, viewportW: window.innerWidth }, tail);
      const bottom = Math.ceil(nightBottom(layout, tail));
      setFit((prev) => (prev && prev.bottom === bottom && sameLayout(prev.layout, layout) ? prev : { layout, bottom }));
    };
    const ro = new ResizeObserver(measure);
    ro.observe(col);
    ro.observe(below);
    ro.observe(inner);
    measure();
    return () => ro.disconnect();
  }, [scene, colRef, stageRef, belowRef]);

  return scene === 'day' ? null : fit;
}

/**
 * La scène (spec §4) : la rosace sur le portail de pierre, la vidéo au seuil, l'horloge dans l'anneau,
 * et dessous le titre et le transport. Une seule mesure, R (useStageLayout), pilote tout par variables CSS ;
 * la nuit, R vient de useNightFit, pour que son texte tienne aussi.
 * `booted` : la session a été vérifiée (page.tsx) ; avant, c'est la nuit « chargement ».
 * Mémoïsée : page.tsx lit tout le store (usePlayer) et se rend à chaque tick du bot ; la scène, elle,
 * ne se rend qu'à ses propres changements (sélecteurs de primitives ci-dessous : `me` et `player.current`
 * sont recréés à chaque charge utile) et une fois par panneau de l'horloge.
 */
function Stage({ booted }: { booted: boolean }) {
  const colRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const belowRef = useRef<HTMLDivElement>(null);
  const loggedIn = useStore((s) => !!s.me);
  const hasCurrent = useStore((s) => !!s.player.current);
  const url = useStore((s) => s.player.current?.url);
  const thumb = useStore((s) => s.player.current?.thumb || s.player.current?.thumbnail || null);
  const nextUrl = useStore((s) => s.player.queue[0]?.url);
  const paused = useStore((s) => s.player.paused);

  const scene = stageScene({ booted, loggedIn, hasCurrent });
  const day = scene === 'day';
  const measured = useStageLayout(colRef, belowRef);
  const nightFit = useNightFit(scene, colRef, stageRef, belowRef);
  const layout = nightFit?.layout ?? measured;
  const dial = useMemo(() => dialGeometry(layout?.c ?? 0.3), [layout?.c]);
  const pane = useStageClock(stageRef, dial.n);
  const [offset, setOffset] = useVideoOffset();
  const videoId = day ? extractVideoId(url) : null;
  const nextId = extractVideoId(nextUrl);
  // Titre sans vidéo YouTube (SoundCloud, que le bot joue aussi) : sa pochette tient lieu d'image.
  const art = day && !videoId ? thumb : null;

  // Filet de sécurité (DESIGN §12.4) : si la scène ou sa nuit débordent malgré tout, la colonne défile.
  useLayoutEffect(() => {
    const col = colRef.current, stage = stageRef.current;
    if (!col || !stage) return;
    const night = stage.querySelector<HTMLElement>('.night');
    const need = Math.max(stage.offsetHeight, night ? night.offsetTop + night.offsetHeight : 0);
    col.dataset.fit = need > col.clientHeight + 1 ? 'loose' : 'tight';
  }, [layout, scene, nightFit]);

  // La nuit, la scène la contient : elle reste centrée dans la colonne et le filet de sécurité la compte.
  const style = (layout
    ? { ...stageCssVars(layout), '--a0': String(dial.a0), minHeight: nightFit ? `${nightFit.bottom}px` : undefined }
    : undefined) as CSSProperties | undefined;

  return (
    <section className="stage-col" ref={colRef} aria-label={day ? t('now.kicker') : undefined}>
      <div className="stage" ref={stageRef} style={style}
        data-scene={day ? 'day' : 'night'} data-paused={day && paused} data-springs={layout?.springs ?? 'spring'}>
        <Rose videoId={videoId} nextId={nextId} R={layout?.R ?? 0} mask={paneMask(day ? pane : -1)}/>
        <div className="lightpool" aria-hidden="true"/>
        <Clock dial={dial} active={day} labelledBy={NOW_TITLE_ID}/>
        {scene !== 'day' && <NightState kind={scene}/>}
        <Portal videoId={videoId} nextId={nextId} paused={paused} offset={offset} art={art}/>
        <div className="below" ref={belowRef}>
          <TimesRow/>
          <div className="now">
            <NowPlaying/>
            <Transport/>
          </div>
          <div className="below-foot">
            <p className="muted-note">
              <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5.5L6.5 9H3.5v6h3l4.5 3.5z"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5"/></svg>
              {t('now.embedMuted')}
            </p>
            {videoId && <SyncOffset value={offset} onChange={setOffset}/>}
          </div>
        </div>
      </div>
    </section>
  );
}

export default memo(Stage);
