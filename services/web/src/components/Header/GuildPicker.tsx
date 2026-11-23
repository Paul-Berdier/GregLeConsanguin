'use client';

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { FocusEvent, KeyboardEvent, MouseEvent } from 'react';
import { playerActions, useStore } from '@/hooks/usePlayer';
import { revealDelta } from '@/lib/focus';
import { filterGuilds, foldText, groupGuilds, guildKey, imeKey, moveIndex, openingActive, searchable } from '@/lib/guilds';
import type { GuildInfo } from '@/lib/types';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';

/**
 * État commun des popovers de l'en-tête (serveurs, compte) : ouverture, fermeture au clic dehors,
 * à la sortie du focus (Tab) et sur Échap, le focus revenant alors au déclencheur. Un Échap déjà traité
 * plus bas (preventDefault : le champ de recherche des serveurs se vide d'abord) laisse le popover ouvert.
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
      if (e.key === 'Escape' && open && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); close(true); }
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

// `lazy` : icônes de la liste, chargées seulement quand le popover les montre (des centaines de serveurs possibles)
function GuildIcon({ guild, lazy, children }: { guild: GuildInfo | null; lazy?: boolean; children?: React.ReactNode }) {
  const [broken, setBroken] = useState(false);
  const icon = guild?.icon && !broken ? `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64` : null;
  return (
    <span className="guild-ico" aria-hidden="true" style={{ background: guild ? tincture(guild.id) : 'var(--voute-2)' }}>
      {icon ? <img src={icon} alt="" width={28} height={28} loading={lazy ? 'lazy' : undefined} decoding="async"
        onError={() => setBroken(true)}/>
        : guild ? (guild.name.trim()[0] || '?').toUpperCase() : '?'}
      {children}
    </span>
  );
}

function gregPresence(g: GuildInfo): string | null {
  if (g.bot_present === true) return tx('guildFilter.present');
  if (g.bot_present === false) return tx('guildFilter.absent');
  return null; // présence inconnue de l'API : rien d'affirmé
}

// Décompte annoncé après une pause de frappe : une annonce par requête, pas une par touche.
const STATUS_DELAY = 500;

/**
 * Choix du serveur : popover à la place de l'ancien <select>. À partir de 8 serveurs (lib/guilds), un champ de
 * recherche en tête (combobox, comme SearchBar) : le focus reste dans le champ, l'option active est désignée par
 * aria-activedescendant. En dessous, même modèle clavier, focus sur la liste elle-même.
 */
export default function GuildPicker() {
  // Sélecteurs étroits : usePlayer() lirait tout le store, et le bot l'écrit 4 fois par seconde (position, horloge) ;
  // avec des centaines de serveurs, chaque option serait redessinée à chaque fois.
  const guilds = useStore((s) => s.guilds);
  const guildId = useStore((s) => s.guildId);
  const socketReady = useStore((s) => s.socketReady);
  const { setGuild } = playerActions;
  const { open, setOpen, close, btnRef, wrapProps } = usePopover();
  const [query, setQuery] = useState('');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const uid = useId();
  const listId = `${uid}-list`;
  const optId = (id: string) => `${uid}-opt-${id}`;
  const headId = (key: string) => `${uid}-head-${key}`;
  const current = guilds.find((g) => g.id === guildId) || null;
  const live = t(socketReady ? 'header.live.on' : 'header.live.off');
  const label = current ? current.name : t('guild.placeholder');

  const withField = searchable(guilds.length);
  const asked = foldText(query) !== '';   // des espaces seuls ne filtrent rien
  const results = useMemo(() => filterGuilds(guilds, query), [guilds, query]);
  const groups = useMemo(() => groupGuilds(results, query), [results, query]);
  const grouped = groups.some((x) => x.key !== 'all');
  const activeIdx = activeId == null ? -1 : results.findIndex((g) => g.id === activeId);
  const activeOpt = open && activeIdx >= 0 ? optId(results[activeIdx].id) : undefined;

  // Le champ s'il existe, sinon la liste : là où vont le focus et les touches
  const focusTarget = () => (withField ? inputRef.current : listRef.current);

  // Ouvert du doigt (ou du stylet) : le focus reste au déclencheur, aucun clavier virtuel ne couvre la liste
  const takeFocus = useRef(true);
  const pointer = useRef('');   // pointeur du dernier appui sur le déclencheur ; '' : clavier

  // Champ vidé à chaque ouverture ; actif : le serveur choisi, sinon le premier (le dernier si ouvert par ↑)
  const openList = (from: 'first' | 'last', focus = true) => {
    setQuery('');
    setActiveId(openingActive(filterGuilds(guilds, ''), guildId, from));
    takeFocus.current = focus;
    setOpen(true);
  };

  // À l'ouverture : liste remontée, focus dans le champ (ou sur la liste) ; l'effet suivant montre l'option active
  useEffect(() => {
    if (!open) return;
    if (listRef.current) listRef.current.scrollTop = 0;
    if (takeFocus.current) focusTarget()?.focus({ preventScroll: true });
  }, [open]);

  // L'option active reste visible, son intertitre avec elle ; seule la liste défile, jamais la page.
  // offsetTop (la liste est positionnée) : juste pendant l'échelle .97 de l'ouverture, que getBoundingClientRect subirait.
  useEffect(() => {
    const list = listRef.current;
    if (!open || !list || activeIdx < 0) return;
    const el = document.getElementById(optId(results[activeIdx].id));
    if (!el) return;
    const prev = el.previousElementSibling as HTMLElement | null;
    const top = (prev?.classList.contains('guild-group') ? prev : el).offsetTop;
    list.scrollTop += revealDelta(top, el.offsetTop + el.offsetHeight, list.scrollTop, list.scrollTop + list.clientHeight);
  }, [open, activeIdx, results]);

  // Nombre de serveurs trouvés (ou l'état vide) dans la région polie, après une pause de frappe
  useEffect(() => {
    if (!open || !asked) { setStatus(''); return; }
    const n = results.length, q = query.trim();
    const id = setTimeout(() => setStatus(n ? tx('guildFilter.count', { n }) : tx('guildFilter.empty', { q })), STATUS_DELAY);
    return () => clearTimeout(id);
  }, [open, asked, query, results.length]);

  const choose = (id: string) => {
    close(true);
    if (id !== guildId) setGuild(id).catch(() => {});
  };

  // Chaque frappe : la meilleure correspondance devient active (Entrée la choisit) ; champ vidé : le serveur choisi
  const onType = (v: string) => {
    setQuery(v);
    const next = filterGuilds(guilds, v);
    setActiveId(foldText(v) ? next[0]?.id ?? null : openingActive(next, guildId, 'first'));
  };

  // Même modèle dans le champ et sur la liste (lib/guilds : guildKey)
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    // Composition en cours (IME, lib/guilds : imeKey) : Entrée, Échap et flèches lui appartiennent. La touche ne remonte
    // pas : l'Échap qui annule une composition ne ferme pas le popover (usePopover).
    if (imeKey(e.nativeEvent)) { e.stopPropagation(); return; }
    const inField = e.currentTarget === inputRef.current;
    const act = guildKey(e, { field: inField, query });
    if (!act) {
      // Lettre tapée sur la liste alors que le champ existe : focus passé au champ pendant keydown, la lettre y tombe,
      // curseur en fin (comme la saisie directe de page.tsx : jamais à l'ancien curseur ni sur une sélection restée là)
      const field = inputRef.current;
      if (field && !inField && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        field.focus();
        const n = field.value.length;
        field.setSelectionRange(n, n);
      }
      return;
    }
    e.preventDefault();
    if (act === 'clear') {
      e.stopPropagation();   // usePopover ne ferme pas : Échap vide d'abord le champ, l'option active reste
      setQuery('');
      if (activeIdx < 0) setActiveId(openingActive(filterGuilds(guilds, ''), guildId, 'first'));
      return;
    }
    if (act === 'choose') { if (activeIdx >= 0) choose(results[activeIdx].id); return; }
    const i = moveIndex(activeIdx, results.length, act);
    setActiveId(i >= 0 ? results[i].id : null);
  };

  const onTriggerClick = () => {
    const by = pointer.current;
    pointer.current = '';
    if (open) close();
    else openList('first', by === '' || by === 'mouse');
  };

  const onTriggerKey = (e: KeyboardEvent) => {
    pointer.current = '';   // Entrée, Espace : un clic du clavier, le focus entre dans le popover
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    if (open) focusTarget()?.focus({ preventScroll: true });
    else openList(e.key === 'ArrowUp' ? 'last' : 'first');
  };

  // Clic dans le popover ailleurs que dans le champ (icône, marges, intertitre, état vide) : le focus reste où il est.
  // Sans cela il tombait sur <body>, popover ouvert : plus de flèches ni d'Échap, et la saisie directe de page.tsx
  // envoyait les lettres à la recherche des titres. La barre de défilement de la liste garde son geste.
  const keepFocus = (e: MouseEvent) => {
    if (e.target !== inputRef.current && e.target !== listRef.current) e.preventDefault();
  };

  // Options sans focus propre (aria-activedescendant) : le clic ne prend pas le focus au champ
  const option = (g: GuildInfo) => {
    const presence = grouped ? null : gregPresence(g);   // intertitres affichés : la présence est déjà dite au-dessus
    return (
      <div key={g.id} id={optId(g.id)} role="option" className="pop-item guild-opt" aria-selected={g.id === guildId}
        data-active={g.id === activeId || undefined} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(g.id)}>
        <GuildIcon guild={g} lazy/>
        <span className="two">
          <b title={g.name}>{g.name}</b>
          {presence && <small data-greg={g.bot_present ? 'present' : 'absent'}>{presence}</small>}
        </span>
      </div>
    );
  };

  return (
    <div className="guild-wrap" {...wrapProps}>
      <button ref={btnRef} type="button" className="chip" aria-haspopup="listbox" aria-expanded={open}
        aria-controls={listId} aria-label={`${t('guild.label')} : ${label} (${live})`} title={t('guild.tooltip')}
        onPointerDown={(e) => { pointer.current = e.pointerType; }} onClick={onTriggerClick} onKeyDown={onTriggerKey}>
        <GuildIcon key={current?.id ?? ''} guild={current}>
          <span className="live" data-on={socketReady} title={live}/>
        </GuildIcon>
        <span className="guild-name">{label}</span>
        <svg className="chev ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 9.5l5.5 5.5 5.5-5.5"/></svg>
      </button>
      <div className="pop plaque guild-pop" data-open={open} style={{ minWidth: 270 }} onMouseDown={keepFocus}>
        {withField ? (
          // <label> : un clic sur la loupe ou les marges du cadre met le focus dans le champ
          <label className="guild-find">
            <svg className="ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.2"/><path d="M15.5 15.5l4.5 4.5"/></svg>
            <input ref={inputRef} type="text" value={query} onChange={(e) => onType(e.target.value)} onKeyDown={onKey}
              placeholder={tx('guildFilter.placeholder')} aria-label={tx('guildFilter.label')}
              autoComplete="off" autoCapitalize="none" spellCheck={false} enterKeyHint="go"
              role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
              aria-activedescendant={activeOpt}/>
          </label>
        ) : (
          <div className="pop-title" aria-hidden="true">{t('guild.label')}</div>
        )}
        <div ref={listRef} id={listId} className="guild-list" role="listbox" aria-label={t('guild.label')} tabIndex={-1}
          aria-activedescendant={activeOpt} onKeyDown={onKey}>
          {guilds.length === 0 && (
            <div className="pop-item" role="option" aria-selected="false" aria-disabled="true">{t('guild.none')}</div>
          )}
          {groups.map(({ key, guilds: list }) => (key === 'all'
            ? <Fragment key={key}>{list.map(option)}</Fragment>
            : (
              <div key={key} role="group" aria-labelledby={headId(key)}>
                <div className="guild-group" id={headId(key)} role="presentation">
                  {key === 'present' ? tx('guildFilter.group.present') : tx('guildFilter.group.absent')}
                </div>
                {list.map(option)}
              </div>
            )))}
        </div>
        {asked && results.length === 0 && <p className="guild-empty">{tx('guildFilter.empty', { q: query.trim() })}</p>}
      </div>
      <div className="sr" role="status">{status}</div>
    </div>
  );
}
