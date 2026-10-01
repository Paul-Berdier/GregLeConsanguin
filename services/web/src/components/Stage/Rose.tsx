'use client';

import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { RoseClient, STONE_URL, afterFirstPaint, roseSupported, watchDpr } from '@/lib/rose/client';
import { BUSY_MS, NIGHT_ROSE_FADE_MS } from '@/lib/stage/coronation';
import type { Ceremony } from './coronation';

export type RoseProps = {
  videoId: string | null;              // titre dont le verre est affiché ; null = clair de lune
  nextId: string | null;               // prochain titre : sa fenêtre est peinte d'avance
  R: number;                           // rayon du vitrail (useStageLayout) ; 0 tant qu'inconnu
  mask: { p0: number; p1: number };    // panneaux de l'horloge déjà joués / courant (paneMask, degrés)
  crown: Ceremony | null;              // cérémonie du titre en cours (coronation.ts) : quand et en combien la rosace se rallume
};

/**
 * La rosace (spec §4) : bloom et verre, deux calques remplis par RoseClient (canevas bitmaprenderer).
 * Décorative : aria-hidden. Moteur sans OffscreenCanvas, ou worker hors service : la pierre seule, immobile (spec §7).
 * La pierre et le worker attendent la première image présentée, puis le premier temps mort (spec §7, afterFirstPaint) :
 * ce qui a été demandé entre-temps part au démarrage. Au Couronnement, la rosace se rallume selon le plan (en vol, à
 * l'atterrissage) et ne peint rien d'avance pendant la cérémonie (un titre sans vidéo aussi) ; à l'arrêt, la lune entre
 * en 240 ms.
 * Styles : rose.css. Le masque de l'horloge passe par --p0 / --p1 sur la racine.
 */
export default function Rose({ videoId, nextId, R, mask, crown }: RoseProps) {
  const bloomRef = useRef<HTMLDivElement>(null);
  const glassRef = useRef<HTMLDivElement>(null);
  const client = useRef<RoseClient | null>(null);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    if (!roseSupported() || !bloomRef.current || !glassRef.current) { setSupported(false); return; }
    // worker hors service (module introuvable, en erreur) : le client s'est vidé, la pierre prend le relais
    const onFail = () => { client.current = null; setSupported(false); };
    const c = new RoseClient({ bloom: bloomRef.current, glass: glassRef.current }, { onFail });
    client.current = c;
    const start = () => { if (client.current === c) c.start(); };
    const cancel = afterFirstPaint(start);
    return () => { cancel(); c.destroy(); client.current = null; };
  }, []);

  // la densité de pixels peut changer seule (autre écran, zoom) : resize(R) la relit et repeint, net
  useEffect(() => {
    if (!R) return;
    client.current?.resize(R);
    return watchDpr(() => client.current?.resize(R));
  }, [R]);

  const crownRef = useRef(crown);
  crownRef.current = crown;
  const shownId = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const c = client.current, was = shownId.current;
    shownId.current = videoId;
    if (!c) return;
    // Un titre sans vidéo (SoundCloud) montre aussi la lune, mais suit son Couronnement ; sans cérémonie, c'est
    // l'arrêt : la lune en 240 ms.
    const plan = crownRef.current?.plan ?? null;
    if (plan) c.hold(BUSY_MS);
    const fade = plan ? plan.roseFade : was ? NIGHT_ROSE_FADE_MS : undefined;
    if (!plan?.roseAt) { void c.show(videoId, fade); return; }
    const tm = setTimeout(() => { void c.show(videoId, fade); }, plan.roseAt);             // en vol : à l'atterrissage
    return () => clearTimeout(tm);
  }, [videoId]);

  // pas de R ici : pendant un redimensionnement, le client repeint le prochain titre une fois la taille posée
  useEffect(() => { client.current?.prepare(nextId); }, [nextId]);

  const style = { '--p0': mask.p0, '--p1': mask.p1 } as CSSProperties;
  return (
    <div className="rosace" aria-hidden="true" style={style}>
      <div className="dim">
        <div className="bloom-layer" ref={bloomRef}/>
        <div className="glass-layer" ref={glassRef}>
          {!supported && (
            <div className="slot" data-kind={videoId ? 'song' : 'moon'}>
              <img className="stone-still" src={STONE_URL} alt="" decoding="async"/>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
