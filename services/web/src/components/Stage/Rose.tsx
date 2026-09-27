'use client';

import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { RoseClient, STONE_URL, roseSupported } from '@/lib/rose/client';

export type RoseProps = {
  videoId: string | null;              // titre dont le verre est affiché ; null = clair de lune
  nextId: string | null;               // prochain titre : sa fenêtre est peinte d'avance
  R: number;                           // rayon du vitrail (useStageLayout) ; 0 tant qu'inconnu
  mask: { p0: number; p1: number };    // panneaux de l'horloge déjà joués / courant (paneMask, degrés)
};

/**
 * La rosace (spec §4) : bloom et verre, deux calques remplis par RoseClient (canevas bitmaprenderer).
 * Décorative : aria-hidden. Moteur sans OffscreenCanvas : la pierre seule, immobile (spec §7).
 * Styles : rose.css. Le masque de l'horloge passe par --p0 / --p1 sur la racine.
 */
export default function Rose({ videoId, nextId, R, mask }: RoseProps) {
  const bloomRef = useRef<HTMLDivElement>(null);
  const glassRef = useRef<HTMLDivElement>(null);
  const client = useRef<RoseClient | null>(null);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    if (!roseSupported() || !bloomRef.current || !glassRef.current) { setSupported(false); return; }
    const c = new RoseClient({ bloom: bloomRef.current, glass: glassRef.current });
    client.current = c;
    c.start();
    return () => { c.destroy(); client.current = null; };
  }, []);

  useEffect(() => { if (R) client.current?.resize(R); }, [R]);
  useEffect(() => { void client.current?.show(videoId); }, [videoId]);
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
