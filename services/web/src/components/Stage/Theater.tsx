'use client';

import { memo, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { playerActions, useStore } from '@/hooks/usePlayer';
import { kingName } from '@/components/Header/KingAvatar';
import { thumbOf } from '@/components/Queue/QueueRow';
import { keyboardFocus } from '@/lib/focus';
import { fmt } from '@/lib/format';
import { livePosition } from '@/lib/playerUtils';
import { createDedupe, createSettle } from '@/lib/queue/drag';
import { kingOrders } from '@/lib/stage/coronation';
import { fmtSpoken } from '@/lib/stage/dial';
import { FS_IDLE_MS, FS_MAX_ROWS, FS_NARROW, createIdle, createWakeTap, fsSwallowClick, inertOthers, loadFsQueue, neighbourKey, progressOf,
  saveFsQueue, trapIndex } from '@/lib/stage/fullscreen';
import { kickerKey, kingSealSrc, requesterKeys, requesterOf } from '@/lib/stage/scene';
import { parseTitle } from '@/lib/titles';
import type { Track } from '@/lib/types';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';
import LikeButton from '@/components/Library/LikeButton';
import Transport from './Transport';

/** Même pas que useStageClock : la barre avance quatre fois par seconde, sans boucle par image (motion.md P4). */
const TICK_MS = 250;
/** Arrêts de Tab de la surcouche ; ceux qui ne sont pas affichés (popover fermé, file masquée) sont écartés à l'usage. */
const TABBABLE = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';
/** Plaques du Héraut hors d'atteinte : repliées sous la pile (inertes), ou sur le départ (comme focusAfterToast, lib/focus.ts). */
const OUT = '[inert], .toast[data-hidden], .toast[data-leaving]';
/** Activité qui réveille les commandes effacées ; l'appui (pointerdown) aussi, à part : au doigt, il ne fait que ça. */
const WAKE = ['pointermove', 'wheel', 'keydown', 'focusin'] as const;

const ICON = {
  exit: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>,
  queue: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 11h16M4 16h8"/><path d="M15.5 14v6l5-3z"/></svg>,
  play: <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13L18.5 12z"/></svg>,
  del: <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>,
};

/** Le Héraut, monté dans l'élément en plein écran à côté de la surcouche (page.tsx) : ses « Annuler » restent à portée. */
function heraldOf(root: HTMLElement): HTMLElement | null {
  return root.parentElement?.querySelector<HTMLElement>(':scope > .toasts') ?? null;
}

/** Ce qui garde le focus en plein écran : la surcouche et le Héraut à côté d'elle ; le reste de la page est hors de l'écran. */
function inside(root: HTMLElement, n: Node): boolean {
  return root.contains(n) || !!heraldOf(root)?.contains(n);
}

/** Arrêts de Tab en plein écran, dans l'ordre du document : ceux de la surcouche, puis les « Annuler » du Héraut. */
function stops(root: HTMLElement): HTMLElement[] {
  return [root, heraldOf(root)].flatMap((box) => (box ? [...box.querySelectorAll<HTMLElement>(TABBABLE)] : []))
    .filter((el) => !el.closest(OUT) && el.getClientRects().length > 0);
}

/**
 * Une ligne de la file en plein écran, au style de la file : pochette, titre nettoyé (le brut en info-bulle), artiste,
 * durée ; « Jouer maintenant » et « Retirer » (clics délégués à la liste, data-act). Le titre en cours ouvre la liste,
 * sans actions. Classes propres (th-*) : les sélecteurs globaux de la file (.qlist > .row, #pane-queue) ne la voient pas.
 */
const TheaterRow = memo(function TheaterRow({ item, now }: { item: Track; now: boolean }) {
  const p = parseTitle(item.title, item.artist);
  const song = p.song || item.title || '—';
  const thumb = thumbOf(item);
  return (
    <li className="th-row" data-key={item.key} data-current={now || undefined}>
      <span className="th-thumb" aria-hidden="true">
        {thumb && <img src={thumb} alt="" loading="lazy" decoding="async" width={64} height={36} draggable={false}/>}
      </span>
      <span className="th-meta">
        <span className="t" title={item.title}>{song}</span>
        {p.artist && <span className="a">{p.artist}</span>}
      </span>
      <span className="th-side">
        {now ? <span className="th-tag">{tx('fullscreen.current')}</span> : <span className="th-dur tnum">{fmt(item.duration)}</span>}
        {!now && <>
          <button type="button" className="th-act" data-act="play" aria-label={t('queue.actions.playNowAria', { title: song })} title={t('queue.actions.playNow')}>{ICON.play}</button>
          <button type="button" className="th-act del" data-act="del" aria-label={t('queue.actions.removeAria', { title: song })} title={t('queue.actions.remove')}>{ICON.del}</button>
        </>}
      </span>
    </li>
  );
});

/**
 * « La Grand-Salle » (conception du 2026-11-23, §2) : la surcouche de la vidéo en plein écran, dernier enfant de `.video`
 * (Portal.tsx), rendue seulement en plein écran. En haut, ce qui joue (surtitre, titre en Grenze, artiste et demandeur)
 * et les boutons ; à droite, la file « À suivre » sur une plaque translucide, masquable (mémorisé) ; en bas, les temps,
 * la barre de progression et le Transport de la scène. Translucide par la couleur seule : ni flou ni filtre au-dessus de
 * l'iframe (tech.md §6.2). Styles : theater.css.
 * Les commandes s'effacent après 3 s de repos (createIdle), le curseur avec elles ; elles restent pendant un dialogue et
 * tant qu'une d'elles a le focus du clavier. Au doigt, l'appui qui les réveille ne les actionne pas (createWakeTap).
 * Focus : la surcouche le prend à l'entrée (Espace y met encore en pause : sur un bouton, il l'activerait), Tab y tourne
 * en boucle avec les « Annuler » du Héraut monté à côté, et un focus égaré ailleurs (hors de l'écran) y revient ; le
 * reste de la page est inerte (inertOthers). À la sortie, Stage.tsx le rend au bouton d'entrée.
 * Les temps sont écrits par useStageClock (data-clock, sous .stage) ; la barre, ici, au même pas.
 */
export default function Theater({ exit }: { exit: () => void }) {
  const rootRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const titleId = useId();
  const queueId = useId();
  const queueTitleId = useId();
  const current = useStore((s) => s.player.current);
  const queue = useStore((s) => s.player.queue);
  const paused = useStore((s) => s.player.paused);
  const repeat = useStore((s) => s.player.repeat);
  const me = useStore((s) => s.me);
  // rendue après un geste du Roi, jamais côté serveur : le réglage et la largeur de l'écran se lisent dès le premier rendu
  // (téléphone debout, sans choix du Roi : la file, entre le titre et le transport, couvrirait l'image ; masquée)
  const [queueOn, setQueueOn] = useState(() => loadFsQueue(() => localStorage,
    typeof matchMedia === 'function' && matchMedia(FS_NARROW).matches));
  const [idle, setIdle] = useState(false);
  const [dedupe] = useState(createDedupe);
  const [settle] = useState(createSettle);
  // rendue après un geste du Roi, jamais côté serveur : l'heure de son apparition se lit au premier rendu
  const [shownAt] = useState(() => performance.now());

  const parsed = current ? parseTitle(current.title, current.artist) : null;
  const song = parsed?.song || current?.title || '';
  const req = current ? requesterOf(current.addedBy, me?.id) : null;
  const keys = req ? requesterKeys(req) : null;
  const vars = req?.kind === 'other' ? { name: req.name } : undefined;
  const shown = queue.length > FS_MAX_ROWS ? queue.slice(0, FS_MAX_ROWS) : queue;
  const more = queue.length - shown.length;

  // Entrée : le focus dans la surcouche ; un focus parti ailleurs (lecteur d'écran, autre code) y revient : le reste de
  // la page est hors de l'écran. Le Héraut monté à côté (page.tsx) garde le sien : « Annuler », Échap sur une plaque.
  // Un focus tombé sur <body> (« Annuler » joué, plaque partie : le Héraut le rendrait à la file, inerte ici) revient
  // à la surcouche, une tâche plus tard (fenêtre quittée : activeElement ne change pas, rien à faire).
  // Tab et Maj+Tab tournent dans la surcouche puis le Héraut (ordre du document), d'où que parte la touche.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.focus({ preventScroll: true });
    const onFocusIn = (e: FocusEvent): void => {
      if (e.target instanceof Node && !inside(root, e.target)) root.focus({ preventScroll: true });
    };
    const onFocusOut = (e: FocusEvent): void => {
      if (e.relatedTarget) return;
      window.setTimeout(() => {
        const at = document.activeElement;
        if (root.isConnected && (!at || at === document.body)) root.focus({ preventScroll: true });
      }, 0);
    };
    const onKeyDown = (e: globalThis.KeyboardEvent): void => {
      if (e.key !== 'Tab' || e.altKey || e.ctrlKey || e.metaKey) return;
      const list = stops(root);
      const i = trapIndex(list.length, list.indexOf(document.activeElement as HTMLElement), e.shiftKey);
      e.preventDefault();
      (i < 0 ? root : list[i]).focus();
    };
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', onFocusOut);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  // Le reste de la page, hors de l'écran, devient inerte (inertOthers) : ni le focus ni le curseur d'un lecteur d'écran
  // ne s'y égarent ; `.video` (la surcouche, le Héraut) reste vivante. Tout revient à la sortie, avant le focus rendu.
  useEffect(() => {
    const host = rootRef.current?.parentElement;
    return host ? inertOthers(host, document.body) : undefined;
  }, []);

  // Repos : commandes et curseur s'effacent après 3 s ; un dialogue ouvert (confirmation d'arrêt), une commande qui a le
  // focus du clavier (son anneau ne s'efface pas avec elle, WCAG 2.4.7) ou, à la souris, le pointeur posé sur une
  // commande les retient : boutons du haut, file, transport, pas les bandeaux entiers (au toucher, le survol reste collé
  // après un appui : il ne compte pas ; un bouton touché ou cliqué garde le focus, sans :focus-visible : il ne compte pas).
  // Au doigt, l'appui sur des commandes effacées les réveille seulement : le clic qui suit, lancé au lever du doigt sur
  // la commande tout juste revenue, est avalé en capture (createWakeTap), avant elle et React.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const fine = typeof matchMedia === 'function' ? matchMedia('(hover: hover) and (pointer: fine)') : null;
    const keyed = (): boolean => {
      const el = document.activeElement;
      return el instanceof HTMLElement && root.contains(el) && !!el.closest('.th-ui') && keyboardFocus(el);
    };
    const hold = (): boolean => !!root.querySelector('.pop[data-open="true"]') || keyed()
      || (!!fine?.matches && !!root.querySelector('.th-acts:hover, .th-queue:hover, .th-bottom .transport:hover'));
    const rest = createIdle(FS_IDLE_MS, setIdle, hold, { set: (fn, ms) => window.setTimeout(fn, ms), clear: (h) => window.clearTimeout(h as number) });
    const tap = createWakeTap();
    const wake = (): void => rest.wake();
    const down = (e: PointerEvent): void => { tap.down(e.pointerType, rest.idle); rest.wake(); };
    const cancel = (): void => tap.cancel();
    const eat = (e: globalThis.MouseEvent): void => {
      if (!tap.eats(e.detail)) return;
      e.preventDefault();
      e.stopPropagation();
    };
    for (const ev of WAKE) root.addEventListener(ev, wake, { passive: true });
    root.addEventListener('pointerdown', down, { passive: true });
    root.addEventListener('pointercancel', cancel);
    root.addEventListener('click', eat, true);
    rest.wake();
    return () => {
      for (const ev of WAKE) root.removeEventListener(ev, wake);
      root.removeEventListener('pointerdown', down);
      root.removeEventListener('pointercancel', cancel);
      root.removeEventListener('click', eat, true);
      rest.stop();
    };
  }, []);

  // Barre de progression (lecture seule : le bot n'a pas de seek), en transform ; son aria comme l'horloge de la scène.
  useEffect(() => {
    let spoken = '';
    const tick = (): void => {
      const s = useStore.getState(), track = s.player.current;
      const dur = track ? s.tickBase.dur || s.player.duration || track.duration || 0 : 0;
      const pos = track ? livePosition(s.tickBase, s.player.paused, performance.now()) : 0;
      if (fillRef.current) fillRef.current.style.transform = `scaleX(${progressOf(pos, dur)})`;
      const bar = barRef.current, text = track && dur > 0 ? t('now.progressAria', { cur: fmtSpoken(pos), length: fmtSpoken(dur) }) : '';
      if (!bar || text === spoken) return;
      spoken = text;
      bar.setAttribute('aria-valuemax', String(Math.round(dur)));
      bar.setAttribute('aria-valuenow', String(Math.round(Math.min(pos, dur))));
      bar.setAttribute('aria-valuetext', text);
    };
    tick();
    const id = setInterval(tick, TICK_MS);
    return () => clearInterval(id);
  }, []);

  /**
   * Entrée maintenue sur « Retirer » ou « Jouer maintenant » : une fois. Le focus passe à la voisine (même bouton) et
   * chaque répétition la retirerait ou la jouerait à son tour : toute la file y passerait (comme listKey, lib/keys.ts).
   */
  const onListKeyDown = (e: KeyboardEvent<HTMLOListElement>): void => {
    if (e.repeat && e.key === 'Enter' && (e.target as Element).closest('[data-act]')) e.preventDefault();
  };

  /**
   * Second clic d'un double-clic sur « Plein écran » : la surcouche a paru entre les deux, sous le pointeur. Il n'atteint
   * ni la commande dessous (lecture, pause), ni le double-clic de la vidéo (Portal.tsx), qui ferait sortir aussitôt.
   */
  const swallow = (e: MouseEvent<HTMLElement>): void => {
    if (!fsSwallowClick(e.detail, performance.now() - shownAt)) return;
    e.preventDefault();
    e.stopPropagation();
  };

  const toggleQueue = (): void => {
    const next = !queueOn;
    setQueueOn(next);
    saveFsQueue(() => localStorage, next);
  };

  /**
   * « Jouer maintenant » et « Retirer », délégués : actions optimistes de la file (usePlayer). Accalmie comme la file
   * (createSettle, QueuePanel) : la ligne partie, la suivante glisse sous le pointeur immobile ; le second clic d'un
   * double-clic la retirerait ou la jouerait aussi. Au clavier (detail 0), le focus l'a suivie exprès : rien n'attend.
   */
  const onListClick = (e: MouseEvent<HTMLOListElement>): void => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('button[data-act]');
    const key = btn?.closest<HTMLElement>('.th-row')?.dataset.key;
    const act = btn?.dataset.act;
    if (!btn || !key || !act) return;
    const now = performance.now();
    if (e.detail > 0 && settle.active(now)) return;
    if (act === 'play' && dedupe(key, now)) return;
    settle.start(now);
    // la ligne va partir : le focus passe avant à sa voisine (même bouton), sinon il tomberait sur <body>, hors de l'écran
    if (btn === document.activeElement) {
      const near = neighbourKey(shown.map((x) => x.key), key);
      const to = near ? listRef.current?.querySelector<HTMLElement>(`.th-row[data-key="${CSS.escape(near)}"] [data-act="${act}"]`) : null;
      (to ?? rootRef.current)?.focus({ preventScroll: true });
    }
    if (act === 'play') {
      // ordre noté « clavier » : le vol de la pochette vers le portail (Couronnement) passerait hors de l'écran
      kingOrders.mark(key, 'key', performance.now());
      void playerActions.playNow(key);
    } else if (act === 'del') void playerActions.removeTrack(key);
  };

  return (
    <section ref={rootRef} className="theater" aria-label={tx('fullscreen.region')} tabIndex={-1}
      data-idle={idle || undefined} onClickCapture={swallow} onDoubleClickCapture={swallow}>
      <div className="th-top th-ui">
        <div className="th-now">
          <p className="th-kicker">{current && t(kickerKey({ paused, repeat }))}</p>
          <h2 className="th-title" id={titleId} title={current?.title}>{song}</h2>
          <p className="th-meta-line">
            {parsed?.artist && <><span className="th-artist">{parsed.artist}</span><span className="dot-sep" aria-hidden="true"/></>}
            {req && keys && <span className="th-by">
              {req.kind === 'mine' && <img className="th-seal" src={kingSealSrc(kingName(me))} alt="" width={18} height={18} decoding="async"/>}
              <span>{t(keys.plain, vars)}</span>
            </span>}
          </p>
        </div>
        <div className="th-acts">
          {/* le cœur du titre en cours (chansonnier du Roi, §3 de la conception) */}
          <LikeButton track={current} className="th-icon th-like"/>
          <button type="button" className="th-icon" aria-label={tx('fullscreen.queueToggle')} aria-expanded={queueOn}
            aria-controls={queueId} title={tx(queueOn ? 'fullscreen.queueHide' : 'fullscreen.queueShow')} onClick={toggleQueue}>
            {ICON.queue}
          </button>
          <button type="button" className="th-icon" aria-label={tx('fullscreen.exit')} title={tx('fullscreen.exitTip')} onClick={exit}>
            {ICON.exit}
          </button>
        </div>
      </div>

      <aside className="th-queue th-ui" id={queueId} aria-labelledby={queueTitleId} hidden={!queueOn}>
        <h3 className="th-qtitle" id={queueTitleId}>{tx('fullscreen.queue')}</h3>
        <ol className="th-list" ref={listRef} onClick={onListClick} onKeyDown={onListKeyDown}
          onPointerMove={(e) => { settle.move(e.clientX, e.clientY, performance.now()); }}>
          {current && <TheaterRow item={current} now/>}
          {shown.map((x) => <TheaterRow key={x.key} item={x} now={false}/>)}
        </ol>
        {more > 0 && <p className="th-more">{tx('fullscreen.more', { n: more })}</p>}
        {!queue.length && <p className="th-empty">{t('now.upNextNone')}</p>}
      </aside>

      <div className="th-bottom th-ui">
        <div className="th-times tnum">
          <span data-clock="cur" aria-hidden="true"/>
          <div className="th-bar" ref={barRef} role="progressbar" aria-labelledby={titleId} aria-valuemin={0}>
            <span className="th-fill" ref={fillRef}/>
          </div>
          <span data-clock="tot" aria-hidden="true"/>
        </div>
        <Transport/>
      </div>
    </section>
  );
}
