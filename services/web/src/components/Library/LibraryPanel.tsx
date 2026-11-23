'use client';

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { kingName } from '@/components/Header/KingAvatar';
import { thumbOf } from '@/components/Queue/QueueRow';
import { useStore } from '@/hooks/usePlayer';
import { libraryActions, useLibrary } from '@/hooks/useLibrary';
import { useRoving } from '@/hooks/useRoving';
import { LIKES, tracksOf } from '@/lib/library';
import { createDedupe } from '@/lib/queue/drag';
import { kingSealSrc } from '@/lib/stage/scene';
import type { Library, LibraryTrack } from '@/lib/types';
import { tx } from '@/theme/copy.extra';
import NameForm from './NameForm';
import PlaylistView from './PlaylistView';
import { HEART, LIST, PLAY, PLUS, SAVE } from './glyphs';
import { tracksMeta } from './meta';

type Card = { key: string; name: string; tracks: LibraryTrack[] };

/**
 * Vue d'ensemble du chansonnier : « Nouvelle playlist » et « Enregistrer la file » (nom en ligne), puis la liste :
 * la carte des coups de cœur (sigil du cœur, sceau du Roi) et les playlists (nom, nombre de titres, durée), chacune
 * avec « Tout jouer ». Un clic ouvre ; clavier (useRoving) : un arrêt de Tab, ↑ ↓ Début Fin, Entrée ouvre.
 * Une playlist créée prend le focus de sa ligne (gardée montée quand elle reçoit son id : originOf).
 */
function Overview({ lib, onOpen }: { lib: Library; onOpen: (id: string) => void }) {
  const me = useStore((s) => s.me);
  const canSave = useStore((s) => !!s.player.current || s.player.queue.length > 0);
  const [form, setForm] = useState<'new' | 'queue' | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const newRef = useRef<HTMLButtonElement>(null);
  const saveRef = useRef<HTMLButtonElement>(null);
  /** Formulaire annulé : le focus revient au bouton qui l'a ouvert. */
  const backTo = useRef<'new' | 'queue' | null>(null);
  const once = useRef(createDedupe());
  const keysId = useId();
  const seal = me ? kingSealSrc(kingName(me)) : null;

  const cards = useMemo<Card[]>(() => [
    { key: LIKES, name: tx('library.likes'), tracks: lib.likes },
    ...lib.playlists.map((p) => ({ key: p.id, name: p.name, tracks: p.tracks })),
  ], [lib.likes, lib.playlists]);
  const keys = useMemo(() => cards.map((c) => c.key), [cards]);
  const roving = useRoving(listRef, keys, 'key', (act, key) => {
    if (act.kind !== 'activate') return undefined;   // Suppr, Alt+flèches : rien ici (une playlist se supprime dans sa vue, confirmée)
    onOpen(key);
    return null;
  });

  useLayoutEffect(() => {
    if (form || !backTo.current) return;
    (backTo.current === 'queue' ? saveRef : newRef).current?.focus();
    backTo.current = null;
  }, [form]);
  // la playlist créée : sa ligne prend le focus dès qu'elle est rendue
  useLayoutEffect(() => {
    if (!focusKey) return;
    const row = listRef.current?.querySelector<HTMLElement>(`:scope > .row[data-key="${CSS.escape(libraryActions.idOf(focusKey))}"]`);
    if (row) { row.focus(); setFocusKey(null); }
  }, [focusKey, cards]);

  const submit = (raw: string): boolean => {
    if (!libraryActions.nameValid(raw)) return false;
    const made = form === 'queue' ? libraryActions.saveQueue(raw) : libraryActions.createPlaylist(raw);
    if (!made) return false;
    backTo.current = null;
    setForm(null);
    setFocusKey(made.id);
    return true;
  };
  const cancel = () => { backTo.current = form; setForm(null); };

  const onClick = (e: MouseEvent) => {
    const key = (e.target as HTMLElement).closest<HTMLElement>('.row')?.dataset.key;
    const card = key ? cards.find((c) => c.key === key) : null;
    if (!card) return;
    if (!(e.target as HTMLElement).closest('[data-act=play]')) { onOpen(card.key); return; }
    if (!once.current(`all:${card.key}`, performance.now())) void libraryActions.playAll(card.tracks, card.name);   // un double-clic ne joue pas deux fois
  };

  const today = new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' });
  return (
    <>
      {form ? (
        <NameForm initial={form === 'queue' ? tx('library.queueName', { date: today }) : ''}
          submitLabel={tx(form === 'queue' ? 'library.save' : 'library.create')}
          submitAria={tx(form === 'queue' ? 'library.save' : 'library.createAria')} onSubmit={submit} onCancel={cancel}/>
      ) : (
        <div className="lbar">
          <button ref={newRef} type="button" className="lbtn" aria-label={tx('library.newPlaylist')} onClick={() => setForm('new')}>
            {PLUS}{tx('library.newPlaylist')}
          </button>
          <button ref={saveRef} type="button" className="lbtn" disabled={!canSave} aria-label={tx('library.saveQueue')}
            title={tx('library.saveQueueAria')} onClick={() => setForm('queue')}>
            {SAVE}{tx('library.saveQueue')}
          </button>
        </div>
      )}
      <div className="scroller">
        <ol className="qlist lcards" ref={listRef} aria-label={tx('library.list')} aria-describedby={keysId}
          onClick={onClick} onKeyDown={roving.onKeyDown} onFocus={roving.onFocus}>
          {cards.map((c) => {
            const cover = c.key === LIKES ? null : c.tracks.map((x) => thumbOf({ thumb: x.thumb, url: x.url })).find(Boolean);
            const meta = tracksMeta(c.tracks);
            return (
              <li key={libraryActions.originOf(c.key)} className="row lrow" data-key={c.key} aria-label={`${c.name}, ${meta}`}
                tabIndex={roving.tabIndexOf(c.key)}>
                <div className="card">
                  <div className="thumb">
                    <div className="im">{cover
                      ? <img src={cover} alt="" loading="lazy" decoding="async" width={56} height={32} draggable={false}/>
                      : <span className="lsigil" aria-hidden="true">{c.key === LIKES ? HEART : LIST}</span>}</div>
                    {c.key === LIKES && seal && <span className="seal"><img src={seal} alt="" width={23} height={23} loading="lazy" decoding="async" draggable={false}/></span>}
                  </div>
                  <div className="meta">
                    <div className="t">{c.name}</div>
                    <div className="a"><span className="nm tnum">{meta}</span></div>
                  </div>
                  <button type="button" tabIndex={-1} className="lplay" data-act="play" disabled={!c.tracks.length}
                    aria-label={tx('library.playAllAria', { name: c.name })} title={tx('library.playAll')}>{PLAY}</button>
                </div>
              </li>
            );
          })}
        </ol>
        <p id={keysId} className="sr">{tx('library.listKeys')}</p>
        {!lib.playlists.length && <p className="lnote">{tx('library.noPlaylists')}</p>}
      </div>
    </>
  );
}

/**
 * Le chansonnier du Roi, troisième volet du panneau (spec 2026-11-23 §3) : la vue d'ensemble ou une vue ouverte
 * (une playlist, les coups de cœur : useLibrary.open). Le focus suit le changement de vue : le bouton retour d'une
 * vue ouverte, la ligne de la vue quittée au retour (ou la ligne active, si elle a disparu). Une vue disparue
 * (playlist supprimée ailleurs, création refusée) rend la vue d'ensemble. Styles : library.css.
 */
export default function LibraryPanel() {
  const status = useLibrary((s) => s.status);
  const lib = useLibrary((s) => s.lib);
  const open = useLibrary((s) => s.open);
  const paneRef = useRef<HTMLDivElement>(null);
  /** Où va le focus au prochain changement de vue : 'back' (vue ouverte) ou la clé de la ligne à retrouver. */
  const focusNext = useRef<string | null>(null);
  const tracks = tracksOf(lib, open);
  const view = open && tracks ? open : null;

  useEffect(() => { if (open && lib && !tracksOf(lib, open)) libraryActions.setOpen(null); }, [open, lib]);

  /** Vue rendue au passage précédent : une vue disparue sous le Roi se reconnaît à son départ. */
  const shown = useRef<string | null>(null);

  useLayoutEffect(() => {
    const want = focusNext.current, was = shown.current;
    focusNext.current = null;
    shown.current = view;
    const root = paneRef.current;
    if (!root) return;
    // vue ouverte disparue sans geste du Roi (playlist supprimée dans un autre onglet, création refusée) : le focus,
    // tombé sur la page avec elle, revient à la liste ; jamais dans un volet caché
    const at = document.activeElement;
    const lost = !want && !!was && !view && (!at || at === document.body) && !root.closest('[aria-hidden="true"]');
    const to = want ?? (lost ? was : null);
    if (!to) return;
    const el = to === 'back' ? root.querySelector<HTMLElement>('.lback')
      : root.querySelector<HTMLElement>(`.lcards > .row[data-key="${CSS.escape(libraryActions.idOf(to))}"]`)
        ?? root.querySelector<HTMLElement>('.lcards > .row[tabindex="0"]');
    el?.focus();
  }, [view]);

  const openView = (id: string) => { focusNext.current = 'back'; libraryActions.setOpen(id); };
  const back = () => { focusNext.current = view; libraryActions.setOpen(null); };

  if (!lib) {
    return (
      <div className="lpane">
        {status === 'error' ? (
          <div className="hstate">
            <p>{tx('library.failed')}</p>
            <button type="button" className="lbtn" aria-label={tx('library.retry')} onClick={() => void libraryActions.load()}>{tx('library.retry')}</button>
          </div>
        ) : <div className="hstate" role="status"><p>{status === 'off' ? '' : tx('library.loading')}</p></div>}
      </div>
    );
  }
  return (
    <div className="lpane" ref={paneRef}>
      {view && tracks
        ? <PlaylistView key={libraryActions.originOf(view)} id={view} lib={lib} tracks={tracks} onBack={back}/>
        : <Overview lib={lib} onOpen={openView}/>}
    </div>
  );
}
