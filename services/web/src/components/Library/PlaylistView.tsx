'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { usePopover } from '@/components/Header/GuildPicker';
import { speak } from '@/components/Herald/store';
import { requeue } from '@/components/History/useRequeue';
import { useStore } from '@/hooks/usePlayer';
import { libraryActions } from '@/hooks/useLibrary';
import { useRoving } from '@/hooks/useRoving';
import { LIKES, findPlaylist, trackKey } from '@/lib/library';
import { createDedupe, createSettle } from '@/lib/queue/drag';
import type { HistoryItem } from '@/lib/queue/view';
import type { Library, LibraryTrack } from '@/lib/types';
import { parseTitle } from '@/lib/titles';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import LibraryRow from './LibraryRow';
import NameForm from './NameForm';
import { BACK, PEN, PLAY, PLUS, TRASH } from './glyphs';
import { tracksMeta } from './meta';

const songOf = (x: LibraryTrack): string => parseTitle(x.title, x.artist).song || x.title;
/** Un titre du chansonnier tel que requeue (l'historique) le remet dans la file. */
const itemOf = (x: LibraryTrack): HistoryItem => ({
  url: x.url, title: x.title, artist: x.artist ?? undefined, thumb: x.thumb, duration: x.duration, provider: x.provider ?? undefined,
});

export type PlaylistViewProps = {
  /** LIKES ou l'id d'une playlist. */
  id: string;
  lib: Library;
  tracks: LibraryTrack[];
  /** Retour à la vue d'ensemble (le focus va à la ligne de cette vue). */
  onBack: () => void;
};

/**
 * Une playlist (ou les coups de cœur) : retour, nom modifiable en ligne, nombre de titres et durée, « Tout jouer »,
 * « Ajouter le titre en cours », « Supprimer » (confirmé, comme l'arrêt du transport : le focus sur « Garder »).
 * Lignes au style de l'historique (LibraryRow). Clics délégués : « + » ou double-clic remettent dans la file avec
 * Le Sceau (requeue), un par 500 ms ; « Retirer » retire (annonce annulable), puis la liste s'accalmit (settle).
 * Clavier (useRoving) : un arrêt de Tab, ↑ ↓ Début Fin, Entrée ajoute à la file, Suppr retire, Alt+↑ / Alt+↓
 * déplacent (pas dans les coups de cœur, rangés du plus récent au plus ancien) ; touches décrites (aria-describedby).
 * Styles : library.css.
 */
export default function PlaylistView({ id, lib, tracks, onBack }: PlaylistViewProps) {
  const likes = id === LIKES;
  const pl = likes ? null : findPlaylist(lib, id);
  const name = pl?.name ?? tx('library.likes');
  const current = useStore((s) => s.player.current);
  const [renaming, setRenaming] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const confirm = usePopover();
  const noRef = useRef<HTMLButtonElement>(null);
  const renameRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const once = useRef(createDedupe());
  const settleRef = useRef(createSettle());
  const moves = useRef(0);
  const keysId = useId(), titleId = useId(), bodyId = useId();

  const keys = useMemo(() => tracks.map((x) => trackKey(x.url)), [tracks]);
  const byKey = useMemo(() => new Map(tracks.map((x) => [trackKey(x.url), x])), [tracks]);
  const curKey = current?.url ? trackKey(current.url) : '';
  /** « Ajouter le titre en cours » : un titre joue et la vue ne l'a pas encore. */
  const canAdd = !!current && !(curKey && keys.includes(curKey));

  // la confirmation de suppression met le focus sur le choix sûr (DESIGN §7)
  useEffect(() => { if (confirm.open) noRef.current?.focus(); }, [confirm.open]);
  // le nom refermé (validé ou annulé) : le focus revient au crayon
  const wasRenaming = useRef(false);
  useEffect(() => {
    if (wasRenaming.current && !renaming) renameRef.current?.focus();
    wasRenaming.current = renaming;
  }, [renaming]);

  const sourceOf = (k: string): HTMLElement | null =>
    listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-key="${CSS.escape(k)}"] .thumb`) ?? null;
  /** false : un ajout vient d'être fait (moins de 500 ms), celui-ci n'est pas envoyé. */
  const add = (x: LibraryTrack): boolean => {
    if (once.current('add', performance.now())) return false;
    requeue(itemOf(x), sourceOf(trackKey(x.url)));
    return true;
  };
  const remove = (x: LibraryTrack) => (likes ? libraryActions.unlike(x) : libraryActions.removeFromPlaylist(id, x));
  const playAll = () => {
    if (once.current('all', performance.now())) return;
    void libraryActions.playAll(tracks, name);
  };

  const roving = useRoving(listRef, keys, 'key', (act, k, i) => {
    const x = byKey.get(k);
    if (!x) return null;
    if (act.kind === 'activate') { add(x); return null; }
    if (act.kind === 'remove') { void remove(x); return keys[i + 1] ?? keys[i - 1] ?? null; }
    if (act.kind !== 'move' || likes) return undefined;   // Alt+Début : rien ici ; les coups de cœur gardent leur ordre
    // seul le dernier déplacement est annoncé (un précédent, accusé en retard, dirait une place dépassée)
    const n = ++moves.current;
    void libraryActions.moveInPlaylist(id, x, i + act.dir).then((ok) => {
      if (ok && n === moves.current) speak(t('queue.dnd.liveMoved', { title: songOf(x), pos: i + 1 + act.dir, total: keys.length }));
    });
    return undefined;
  });

  /**
   * « Retirer » au pointeur : la ligne suivante remonte sous le pointeur immobile, sa puce montrée ; le second clic d'un
   * double-clic la retirait aussi. La liste s'accalmit comme la file (QueuePanel) : clics, double-clics et puces
   * ignorés 400 ms ou jusqu'à 3 px de mouvement (.qlist.settling, queue.css).
   */
  const settle = () => {
    const list = listRef.current, s = settleRef.current;
    s.start(performance.now());
    list?.classList.add('settling');
    const done = () => { if (!s.active(performance.now())) list?.classList.remove('settling'); };
    const onMove = (e: PointerEvent) => { if (s.move(e.clientX, e.clientY, performance.now())) { done(); window.removeEventListener('pointermove', onMove); } };
    window.addEventListener('pointermove', onMove);
    setTimeout(() => { done(); window.removeEventListener('pointermove', onMove); }, 420);
  };
  const settling = () => settleRef.current.active(performance.now());

  const keyOf = (e: MouseEvent) => (e.target as HTMLElement).closest<HTMLElement>('.row')?.dataset.key ?? '';
  const onClick = (e: MouseEvent) => {
    const k = keyOf(e), x = byKey.get(k);
    if (!x || settling()) return;
    const act = (e.target as HTMLElement).closest<HTMLElement>('[data-act]')?.dataset.act;
    if (act === 'add') add(x);
    else if (act === 'del') { settle(); void remove(x); }
    else setPicked(k);
  };
  const onDoubleClick = (e: MouseEvent) => {
    // accalmie : la puce sans pointeur, le dblclick d'un « Retirer » doublé viserait la ligne remontée dessous
    if (settling() || (e.target as HTMLElement).closest('[data-act]')) return;
    const x = byKey.get(keyOf(e));
    if (x) add(x);
  };

  const rename = (raw: string): boolean => {
    if (!libraryActions.nameValid(raw)) return false;
    void libraryActions.renamePlaylist(id, raw);
    setRenaming(false);
    return true;
  };
  const destroy = () => {
    confirm.close();
    void libraryActions.deletePlaylist(id);
    onBack();
  };

  return (
    <div className="lview">
      <div className="lhead">
        <button type="button" className="lback" onClick={onBack} aria-label={tx('library.back')}>{BACK}<span>{tx('library.tab')}</span></button>
        {renaming && pl
          ? <NameForm initial={pl.name} submitLabel={tx('library.save')} submitAria={tx('library.save')} onSubmit={rename} onCancel={() => setRenaming(false)}/>
          : (
            <div className="lname-row">
              <h3 className="lname">{name}</h3>
              {pl && <button ref={renameRef} type="button" className="lbtn licon" aria-label={tx('library.rename')} title={tx('library.rename')}
                onClick={() => setRenaming(true)}>{PEN}</button>}
            </div>
          )}
        <p className="lmeta tnum">{tracksMeta(tracks)}</p>
        <div className="lbar">
          <button type="button" className="lbtn primary" disabled={!tracks.length} aria-label={tx('library.playAllAria', { name })} onClick={playAll}>
            {PLAY}{tx('library.playAll')}
          </button>
          {/* aria-disabled, pas disabled : le titre ajouté, le bouton garde le focus (désactivé, il le perdait sur la page,
              et l'Espace suivant mettait tout le salon en pause) */}
          <button type="button" className="lbtn" aria-disabled={!canAdd} aria-label={tx('library.addCurrent')}
            onClick={() => { if (canAdd && current) void libraryActions.addTo(id, current); }}>
            {PLUS}{tx('library.addCurrent')}
          </button>
          {pl && (
            <div className="ldel" {...confirm.wrapProps}>
              <button ref={confirm.btnRef} type="button" className="lbtn licon danger" aria-label={tx('library.deleteAria', { name })}
                title={tx('library.delete')} aria-haspopup="dialog" aria-expanded={confirm.open} onClick={() => confirm.setOpen((o) => !o)}>
                {TRASH}
              </button>
              <div className="pop plaque lconfirm" role="dialog" aria-labelledby={titleId} aria-describedby={bodyId} data-open={confirm.open}>
                <h3 id={titleId}>{tx('library.confirm.title', { name })}</h3>
                <p id={bodyId}>{tracks.length ? tx('library.confirm.body', { n: tracks.length }) : tx('library.confirm.bodyEmpty')}</p>
                <div className="row-btns">
                  <button ref={noRef} type="button" className="btn-ghost" aria-label={tx('library.confirm.no')} onClick={() => confirm.close(true)}>
                    {tx('library.confirm.no')}
                  </button>
                  <button type="button" className="btn-danger" aria-label={tx('library.confirm.yes')} onClick={destroy}>{tx('library.confirm.yes')}</button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="scroller">
        {tracks.length ? (
          <>
            <ol className="qlist lrows" ref={listRef} aria-label={tx('library.tracks', { name })} aria-describedby={keysId}
              onClick={onClick} onDoubleClick={onDoubleClick} onKeyDown={roving.onKeyDown} onFocus={roving.onFocus}>
              {tracks.map((x, i) => (
                <LibraryRow key={keys[i]} track={x} index={i} likes={likes} picked={picked === keys[i]} tabIndex={roving.tabIndexOf(keys[i])}/>
              ))}
            </ol>
            <p id={keysId} className="sr">{tx(likes ? 'library.keysLikes' : 'library.keys')}</p>
          </>
        ) : <div className="hstate"><p>{tx(likes ? 'library.emptyLikes' : 'library.emptyPlaylist')}</p></div>}
      </div>
    </div>
  );
}
