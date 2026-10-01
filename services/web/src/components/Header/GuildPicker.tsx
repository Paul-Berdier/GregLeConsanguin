'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { FocusEvent, KeyboardEvent } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { t } from '@/theme/copy';
import type { GuildInfo } from '@/lib/types';

/**
 * État commun des popovers de l'en-tête (serveurs, compte) : ouverture, fermeture au clic dehors,
 * à la sortie du focus (Tab) et sur Échap, le focus revenant alors au déclencheur.
 */
export function usePopover() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const close = useCallback((refocus = false) => {
    setOpen(false);
    if (refocus) btnRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => { if (!wrapRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  const wrapProps = {
    ref: wrapRef,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); close(true); }
    },
    // Focus parti ailleurs au clavier ; un clic dans le vide du popover (relatedTarget nul) ne ferme pas
    onBlur: (e: FocusEvent) => {
      const next = e.relatedTarget as Node | null;
      if (next && !wrapRef.current?.contains(next)) setOpen(false);
    },
  };

  return { open, setOpen, close, btnRef, wrapProps };
}

// Émaux pour l'écu d'un serveur sans icône (or, gueules, azur, sinople, pourpre), choisis d'après l'id.
const TINCTURES = ['#cfa75a', '#e0583e', '#6f8fd6', '#5fae7e', '#b27cc0'];
function tincture(id: string): string {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return TINCTURES[h % TINCTURES.length];
}

function GuildIcon({ guild, children }: { guild: GuildInfo | null; children?: React.ReactNode }) {
  const [broken, setBroken] = useState(false);
  const icon = guild?.icon && !broken ? `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64` : null;
  return (
    <span className="guild-ico" aria-hidden="true" style={{ background: guild ? tincture(guild.id) : 'var(--voute-2)' }}>
      {icon ? <img src={icon} alt="" width={28} height={28} decoding="async" onError={() => setBroken(true)}/>
        : guild ? (guild.name.trim()[0] || '?').toUpperCase() : '?'}
      {children}
    </span>
  );
}

// Serveurs sélectionnables (l'état vide « aucun serveur » est désactivé)
function options(list: HTMLElement | null): HTMLButtonElement[] {
  return Array.from(list?.querySelectorAll<HTMLButtonElement>('button[role=option]') ?? []);
}

function gregPresence(g: GuildInfo): string | null {
  if (g.bot_present === true) return 'Greg présent';
  if (g.bot_present === false) return 'Greg absent';
  return null; // présence inconnue de l'API : rien d'affirmé
}

/** Choix du serveur : popover (listbox) à la place de l'ancien <select>, navigable au clavier. */
export default function GuildPicker() {
  const { guilds, guildId, setGuild, socketReady } = usePlayer();
  const { open, setOpen, close, btnRef, wrapProps } = usePopover();
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const current = guilds.find((g) => g.id === guildId) || null;
  const live = t(socketReady ? 'header.live.on' : 'header.live.off');
  const label = current ? current.name : t('guild.placeholder');

  const focusAt = (i: number) => {
    const opts = options(listRef.current);
    if (opts.length) opts[(i + opts.length) % opts.length].focus();
  };

  // À l'ouverture : focus sur le serveur courant (sinon le premier, ou le dernier si ouvert par ↑)
  const openFrom = useRef<'first' | 'last'>('first');
  useEffect(() => {
    if (!open) return;
    const opts = options(listRef.current);
    if (!opts.length) return;
    const sel = opts.findIndex((o) => o.getAttribute('aria-selected') === 'true');
    opts[sel >= 0 ? sel : openFrom.current === 'last' ? opts.length - 1 : 0].focus();
  }, [open]);

  const choose = (id: string) => {
    close(true);
    if (id !== guildId) setGuild(id).catch(() => {});
  };

  const onTriggerKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      openFrom.current = e.key === 'ArrowUp' ? 'last' : 'first';
      setOpen(true);
    }
  };

  const onListKey = (e: KeyboardEvent) => {
    const opts = options(listRef.current);
    const i = opts.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(i + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(i < 0 ? -1 : i - 1); }
    else if (e.key === 'Home') { e.preventDefault(); focusAt(0); }
    else if (e.key === 'End') { e.preventDefault(); focusAt(-1); }
  };

  return (
    <div {...wrapProps}>
      <button ref={btnRef} type="button" className="chip" aria-haspopup="listbox" aria-expanded={open}
        aria-controls={listId} aria-label={`${t('guild.label')} : ${label} (${live})`} title={t('guild.tooltip')}
        onClick={() => { openFrom.current = 'first'; setOpen((o) => !o); }} onKeyDown={onTriggerKey}>
        <GuildIcon key={current?.id ?? ''} guild={current}>
          <span className="live" data-on={socketReady} title={live}/>
        </GuildIcon>
        <span className="guild-name">{label}</span>
        <svg className="chev ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 9.5l5.5 5.5 5.5-5.5"/></svg>
      </button>
      <div ref={listRef} id={listId} className="pop plaque" role="listbox" aria-label={t('guild.label')}
        data-open={open} style={{ minWidth: 270 }} onKeyDown={onListKey}>
        <div className="pop-title" aria-hidden="true">{t('guild.label')}</div>
        {guilds.length === 0 && (
          <div className="pop-item" role="option" aria-selected="false" aria-disabled="true">{t('guild.none')}</div>
        )}
        {guilds.map((g) => {
          const presence = gregPresence(g);
          return (
            <button key={g.id} type="button" role="option" className="pop-item" tabIndex={-1}
              aria-selected={g.id === guildId} onClick={() => choose(g.id)}>
              <GuildIcon guild={g}/>
              <span className="two">
                <b>{g.name}</b>
                {presence && <small data-greg={g.bot_present ? 'present' : 'absent'}>{presence}</small>}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
