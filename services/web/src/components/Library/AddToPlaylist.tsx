'use client';

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { usePopover } from '@/components/Header/GuildPicker';
import { libraryActions, useLibrary } from '@/hooks/useLibrary';
import { heldEnter } from '@/lib/keys';
import { trackKey } from '@/lib/library';
import type { TrackLike } from '@/lib/library';
import { parseTitle } from '@/lib/titles';
import { tx } from '@/theme/copy.extra';
import NameForm from './NameForm';
import { LIST_ADD, PLUS } from './glyphs';

const MOVES = new Set(['ArrowDown', 'ArrowUp', 'Home', 'End']);

/**
 * « Ajouter à une playlist », à côté du cœur du titre en lecture : un petit dialogue (plaque, comme la confirmation
 * d'arrêt du transport) qui liste les playlists du Roi (celles qui l'ont déjà le disent) et « Nouvelle playlist… »
 * (nom en ligne, créée avec le titre). Ouvert : focus sur la première playlist ; ↑ ↓ Début Fin passent d'un choix à
 * l'autre ; Échap ferme et rend le focus au bouton (usePopover), ou referme d'abord le champ du nom. Entrée maintenue
 * n'agit qu'une fois (heldEnter). Il s'ouvre vers le haut, au-dessus de la vidéo (rien ne déborde sous la scène).
 * Styles : library.css (.lmenu), now.css (.nbtn).
 */
export default function AddToPlaylist({ track, className = 'nbtn' }: { track: TrackLike | null; className?: string }) {
  const pop = usePopover();
  const lib = useLibrary((s) => s.lib);
  const [naming, setNaming] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const k = track?.url ? trackKey(track.url) : '';
  const song = track ? parseTitle(track.title, track.artist).song || track.title || '' : '';
  const items = useMemo(() => (lib?.playlists ?? []).map((p) => ({
    id: p.id, name: p.name,
    sub: k && p.tracks.some((x) => trackKey(x.url) === k) ? null
      : p.tracks.length ? tx('library.count.tracks', { n: p.tracks.length }) : tx('library.count.tracksNone'),
  })), [lib, k]);

  const { open, close } = pop;
  const wrapRef = pop.wrapProps.ref, btnRef = pop.btnRef;
  // ouvert : la plaque reste dans la fenêtre (16 px de marge). Ancrée au bouton, elle se décale vers la gauche quand
  // le bouton finit une longue ligne (sur un téléphone, elle sortait de l'écran à droite, coupée par la scène).
  useLayoutEffect(() => {
    const el = panelRef.current, anchor = el?.parentElement;
    if (!open || !el || !anchor) return;
    const x = anchor.getBoundingClientRect().left, vw = document.documentElement.clientWidth;
    el.style.setProperty('--lmenu-dx', `${Math.round(Math.max(16 - x, Math.min(0, vw - 16 - x - el.offsetWidth)))}px`);
  }, [open]);
  // ouvert : le focus sur la première playlist qui peut le recevoir (sinon « Nouvelle playlist… ») ; fermé : le nom repart
  useEffect(() => {
    if (!open) { setNaming(false); return; }
    panelRef.current?.querySelector<HTMLElement>('.pop-item:not([aria-disabled=true])')?.focus();
  }, [open]);
  // le titre a changé sous le menu : ses choix ne valent plus pour lui ; le focus, s'il y était, revient au bouton
  useEffect(() => {
    const at = document.activeElement;
    close(!!at && at !== btnRef.current && !!wrapRef.current?.contains(at));
  }, [k, close, wrapRef, btnRef]);

  const pick = (id: string) => {
    if (!track || !open) return;   // un second clic pendant le fondu de fermeture : déjà ajouté
    close(true);
    void libraryActions.addToPlaylist(id, [track]);
  };
  const create = (name: string): boolean => {
    if (!track || !libraryActions.nameValid(name) || !libraryActions.createPlaylistWith(name, track)) return false;
    close(true);
    return true;
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!MOVES.has(e.key) || (e.target as HTMLElement).closest('input')) return;
    const all = Array.from(panelRef.current?.querySelectorAll<HTMLElement>('.pop-item') ?? []);
    if (!all.length) return;
    e.preventDefault();
    const i = all.indexOf(document.activeElement as HTMLElement);
    const j = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1
      : Math.max(0, Math.min(all.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)));
    all[j]?.focus();
  };

  return (
    // Entrée maintenue (heldEnter) : sans cette garde, chaque répétition ajoutait le titre, rouvrait le menu sur la
    // playlist suivante, et ainsi de suite jusqu'à envoyer un nom vide en boucle
    <div className="ladd" {...pop.wrapProps} onKeyDownCapture={(e) => { if (heldEnter(e)) e.preventDefault(); }}>
      <button ref={pop.btnRef} type="button" className={className} disabled={!k || !lib} aria-haspopup="dialog" aria-expanded={open}
        aria-label={tx('library.addTo.aria', { title: song })} title={tx('library.addTo.label')} onClick={() => pop.setOpen((o) => !o)}>
        {LIST_ADD}
      </button>
      <div className="pop plaque lmenu" ref={panelRef} role="dialog" aria-labelledby={titleId} data-open={open} onKeyDown={onKey}>
        <div className="pop-title" id={titleId}>{tx('library.addTo.label')}</div>
        {items.length ? (
          <ul className="lmenu-list">
            {items.map((it) => (
              <li key={libraryActions.originOf(it.id)}>
                <button type="button" className="pop-item" aria-disabled={!it.sub || undefined}
                  aria-label={`${it.name}, ${it.sub ?? tx('library.addTo.already')}`} onClick={() => { if (it.sub) pick(it.id); }}>
                  <span className="two"><b>{it.name}</b><small>{it.sub ?? tx('library.addTo.already')}</small></span>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="lmenu-none">{tx('library.addTo.none')}</p>}
        <div className="pop-sep" aria-hidden="true"/>
        {naming
          ? <NameForm initial="" submitLabel={tx('library.create')} submitAria={tx('library.createAria')} onSubmit={create}
              onCancel={() => { setNaming(false); requestAnimationFrame(() => panelRef.current?.querySelector<HTMLElement>('.lnew')?.focus()); }}/>
          : <button type="button" className="pop-item lnew" aria-label={tx('library.newPlaylistMenu')} onClick={() => { if (open) setNaming(true); }}>
              {PLUS}{tx('library.newPlaylistMenu')}
            </button>}
      </div>
    </div>
  );
}
