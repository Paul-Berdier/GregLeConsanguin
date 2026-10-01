'use client';

import { Fragment, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { HELP_EVENT, SHORTCUTS_STORAGE_KEY, shortcutsOn } from '@/lib/keys';
import { QUIPS_STORAGE_KEY, quipsOn } from '@/lib/prefs';
import { t } from '@/theme/copy';
import { KEYS, tx } from '@/theme/copy.extra';
import { speak } from '@/components/Herald/store';
import KingAvatar, { kingName } from './KingAvatar';
import { usePopover } from './GuildPicker';

// Réglage « Répliques de Greg » (lib/prefs) : <html data-quips> est posé dès le <head> (layout.tsx), connecté ou non ;
// le menu le bascule. Lu dès le premier rendu : un « on » par défaut écraserait un instant le « off » du <head>.
function readQuips(): boolean {
  try { return quipsOn(localStorage.getItem(QUIPS_STORAGE_KEY)); } catch { return true; }
}

// Réglage « Raccourcis clavier » (WCAG 2.1.4) : 'off' coupe les raccourcis d'une touche. Reflété sur <html data-keys> :
// page.tsx le lit à chaque touche, header.css n'affiche l'indice « / » que sous data-keys=on.
function readKeys(): boolean { try { return shortcutsOn(localStorage.getItem(SHORTCUTS_STORAGE_KEY)); } catch { return true; } }

/** Compte du Roi : avatar couronné, réglages (répliques, raccourcis), liste des raccourcis, déconnexion. `?` l'ouvre. */
export default function AccountMenu() {
  const { me, logout } = usePlayer();
  const { open, setOpen, close, btnRef, wrapProps } = usePopover();
  const popRef = useRef<HTMLDivElement>(null);
  const popId = useId();
  const quipsId = useId();
  const keysId = useId();
  const [quips, setQuips] = useState(readQuips);   // menu monté une fois le Roi connu : jamais au rendu serveur
  const [keys, setKeys] = useState(true);

  useEffect(() => { setKeys(readKeys()); }, []);
  useEffect(() => { document.documentElement.dataset.quips = quips ? 'on' : 'off'; }, [quips]);
  useEffect(() => { document.documentElement.dataset.keys = keys ? 'on' : 'off'; }, [keys]);

  const toggleQuips = () => {
    const next = !quips;
    setQuips(next);
    try { localStorage.setItem(QUIPS_STORAGE_KEY, next ? 'on' : 'off'); } catch {}
  };

  const toggleKeys = () => {
    const next = !keys;
    setKeys(next);
    try { localStorage.setItem(SHORTCUTS_STORAGE_KEY, next ? 'on' : 'off'); } catch {}
    speak(tx(next ? 'keys.on' : 'keys.off'));
  };

  // « ? » (page.tsx) ouvre ce menu, qui porte la liste des raccourcis
  useEffect(() => {
    const onHelp = () => setOpen(true);
    document.addEventListener(HELP_EVENT, onHelp);
    return () => document.removeEventListener(HELP_EVENT, onHelp);
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
        <button type="button" role="switch" aria-checked={keys} className="pop-item" onClick={toggleKeys}
          aria-labelledby={`${keysId}-l`} aria-describedby={`${keysId}-d`}>
          <span className="two">
            <b id={`${keysId}-l`}>{tx('keys.toggle')}</b>
            <small id={`${keysId}-d`}>{tx('keys.toggleHelp')}</small>
          </span>
          <span className="switch" aria-hidden="true"/>
        </button>
        <div className="pop-sep"/>
        <div className="pop-title">{t('shortcuts.title')}</div>
        <dl className="keys">
          {KEYS.map(([key, label]) => (
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
