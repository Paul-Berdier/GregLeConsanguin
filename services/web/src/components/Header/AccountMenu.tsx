'use client';

import { Fragment, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { isShortcutIgnored } from '@/lib/playerUtils';
import { deck, t } from '@/theme/copy';
import KingAvatar, { kingName } from './KingAvatar';
import { usePopover } from './GuildPicker';

// Réglage « Répliques de Greg » : 'off' les coupe (faits seulement), absent ou 'on' les garde.
// Reflété sur <html data-quips> pour les composants qui en affichent.
const QUIPS_KEY = 'greg.webplayer.quips';

function readQuips(): boolean {
  try { return localStorage.getItem(QUIPS_KEY) !== 'off'; } catch { return true; }
}

const SHORTCUTS: [string, string][] = Array.isArray(deck.shortcuts?.items) ? deck.shortcuts.items : [];

/** Compte du Roi : avatar couronné, réglage des répliques, raccourcis, déconnexion. `?` l'ouvre. */
export default function AccountMenu() {
  const { me, logout } = usePlayer();
  const { open, setOpen, close, btnRef, wrapProps } = usePopover();
  const popRef = useRef<HTMLDivElement>(null);
  const popId = useId();
  const quipsId = useId();
  const [quips, setQuips] = useState(true);

  useEffect(() => { setQuips(readQuips()); }, []);
  useEffect(() => { document.documentElement.dataset.quips = quips ? 'on' : 'off'; }, [quips]);

  const toggleQuips = () => {
    const next = !quips;
    setQuips(next);
    try { localStorage.setItem(QUIPS_KEY, next ? 'on' : 'off'); } catch {}
  };

  // « ? » ailleurs que dans un champ : ouvre ce menu, qui porte la liste des raccourcis
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== '?' || isShortcutIgnored(e)) return;
      e.preventDefault();
      setOpen(true);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [setOpen]);

  // À l'ouverture : focus sur la première commande
  useEffect(() => {
    if (open) popRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }, [open]);

  // ↑ ↓ passent d'une commande à l'autre (Tab marche aussi)
  const onPopKey = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = Array.from(popRef.current?.querySelectorAll<HTMLButtonElement>('button') ?? []);
    if (!items.length) return;
    e.preventDefault();
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    const step = e.key === 'ArrowDown' ? 1 : -1;
    items[(i + step + items.length) % items.length].focus();
  };

  if (!me) return null;
  const name = kingName(me);

  return (
    <div {...wrapProps}>
      <button ref={btnRef} type="button" className="chip" style={{ paddingLeft: 3 }} aria-haspopup="dialog"
        aria-expanded={open} aria-controls={popId} aria-label={t('header.account.aria', { kingName: name })}
        onClick={() => setOpen((o) => !o)}>
        <KingAvatar me={me}/>
      </button>
      <div ref={popRef} id={popId} className="pop plaque" role="dialog" aria-label={t('header.account.aria', { kingName: name })}
        data-open={open} style={{ minWidth: 290 }} onKeyDown={onPopKey}>
        <div className="pop-title">{t('header.account.kicker')} · {name}</div>
        {/* Nom : l'intitulé seul ; l'aide (« Désactivées : … ») en description, pas dans le nom */}
        <button type="button" role="switch" aria-checked={quips} className="pop-item" onClick={toggleQuips}
          aria-labelledby={`${quipsId}-l`} aria-describedby={`${quipsId}-d`}>
          <span className="two">
            <b id={`${quipsId}-l`}>{t('header.settings.quips')}</b>
            <small id={`${quipsId}-d`}>{t('header.settings.quipsHelp')}</small>
          </span>
          <span className="switch" aria-hidden="true"/>
        </button>
        <div className="pop-sep"/>
        <div className="pop-title">{t('shortcuts.title')}</div>
        <dl className="keys">
          {SHORTCUTS.map(([key, label]) => (
            <Fragment key={key}>
              <dt><kbd>{key}</kbd></dt>
              <dd>{label}</dd>
            </Fragment>
          ))}
        </dl>
        <div className="pop-sep"/>
        {/* Focus rendu à l'avatar : il y reste si la déconnexion échoue ; sinon l'en-tête
            le passe à « Se connecter » quand le compte disparaît (Header.tsx). */}
        <button type="button" className="pop-item" onClick={() => { close(true); logout().catch(() => {}); }}>
          <svg className="ico" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M14.5 4.5h5v15h-5M10 16.5l4.5-4.5L10 7.5M14.5 12H3.5"/>
          </svg>
          {t('header.logout')}
        </button>
      </div>
    </div>
  );
}
