'use client';

import { useState, useRef, useCallback, useEffect, useId } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { looksLikeUrl, enterPicksSuggestion } from '@/lib/playerUtils';
import { fmt } from '@/lib/format';
import { reducedMotion } from '@/lib/motion';
import { sealBook } from '@/lib/queue/seal';
import { boxOf } from '@/lib/stage/coronation';
import { classifyLink, submitLabelKey, isBadLink } from '@/lib/links';
import type { LinkKind } from '@/lib/links';
import type { SearchResult } from '@/lib/types';
import { I } from '@/components/icons';
import { t } from '@/theme/copy';

// Libellés possibles du bouton, tous rendus dans la même case (header.css) : il ne change pas de largeur.
const SUBMIT_KEYS = ['search.submit.default', 'search.submit.playlist', 'search.submit.mix'] as const;

// Le deck dit « Chaîne YouTube (non prise en charge) », mais le bot ajoute les derniers titres d'une
// chaîne comme une playlist (is_playlist_or_mix_url) : pastille neutre, sans la mention.
const CHANNEL_PILL = 'Chaîne YouTube';
function pillText(kind: LinkKind): string {
  if (kind === 'none') return '';
  return kind === 'channel' ? CHANNEL_PILL : t(`search.linkKind.${kind}`);
}

// Placeholder court là où le champ est étroit : téléphone (prototype : ≤ 520 px), et de 901 à 1100 px,
// où la marque et le compte partagent encore la ligne avec la recherche.
const NARROW_FIELD = '(max-width: 520px), (min-width: 901px) and (max-width: 1100px)';

function useMedia(query: string) {
  const [match, setMatch] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [query]);
  return match;
}

// ═══════════════════════════════
// Search Bar
// ═══════════════════════════════
export default function SearchBar() {
  const { enqueue } = usePlayer();
  const [q, setQ] = useState('');
  const [sugs, setSugs] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const timer = useRef<any>(null);
  const qRef = useRef('');
  const busyRef = useRef(false);
  const searchSeq = useRef(0); // invalide les autocomplétions en vol (saisie suivante / envoi)
  const inputRef = useRef<HTMLInputElement>(null);
  const lastSugs = useRef<SearchResult[]>([]); // liste gardée le temps du fondu de fermeture
  const narrow = useMedia(NARROW_FIELD);
  const uid = useId();
  const kind = classifyLink(q);

  const doSearch = useCallback(async (query: string) => {
    if (query.length < 2 || looksLikeUrl(query)) { setSugs([]); setOpen(false); setSearching(false); return; }
    const my = ++searchSeq.current;
    setSearching(true);
    try {
      const rows = await api.autocomplete(query, 6);
      if (my !== searchSeq.current) return;
      if (qRef.current.trim() === query.trim() && Array.isArray(rows) && rows.length) {
        lastSugs.current = rows;
        setSugs(rows); setOpen(true); setIdx(-1);
      } else if (qRef.current.trim() === query.trim()) { setSugs([]); setOpen(false); }
    } catch {} finally { if (my === searchSeq.current) setSearching(false); }
  }, []);

  const cancelSearch = () => {
    clearTimeout(timer.current);
    searchSeq.current++;
    setSearching(false);
  };

  const onInput = (v: string) => {
    setQ(v); qRef.current = v;
    setIdx(-1); // l'ancienne sélection ne correspond plus au texte
    cancelSearch();
    // Lien collé : jamais d'autocomplétion, il sera envoyé tel quel
    if (v.trim().length < 2 || looksLikeUrl(v)) { setSugs([]); setOpen(false); return; }
    setSearching(true);
    timer.current = setTimeout(() => doSearch(v.trim()), 280);
  };

  // Le Sceau (DESIGN §5) : l'ajout du Roi est attendu, reconnu à l'entrée de sa ligne (QueuePanel).
  // `from` : la pochette de la suggestion, d'où part le vol du sceau (aucun vol en mouvement réduit).
  const expectSeal = (url: string | null, from: Element | null | undefined, thumb: string | null) =>
    sealBook.expect({ url, from: from && !reducedMotion() ? boxOf(from) : null, thumb, at: performance.now() });

  // `typed` : texte du champ au moment de l'envoi — gardé jusqu'au succès, restauré en cas d'échec
  const submit = async (payload: Record<string, any>, typed: string) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
    cancelSearch(); setOpen(false); setSugs([]); setIdx(-1);
    try {
      const ok = await enqueue(payload);
      if (!ok) sealBook.clear();   // rien n'est parti : aucune ligne ne viendra
      if (ok && qRef.current === typed) { setQ(''); qRef.current = ''; }
    } catch {
      sealBook.clear();
      // Statut d'erreur déjà affiché par enqueue : on remet le texte si le champ a été vidé
      if (!qRef.current.trim()) { setQ(typed); qRef.current = typed; }
    } finally {
      busyRef.current = false; setBusy(false);
    }
  };

  const pick = (sug: SearchResult, from?: Element | null) => {
    if (busyRef.current) return;   // un ajout en vol : son sceau attendu reste le sien
    const url = sug.webpage_url || sug.url || '';
    expectSeal(url || null, from, sug.thumb || sug.thumbnail || null);
    submit({ query: url || sug.title, url, webpage_url: url, title: sug.title,
      artist: sug.artist || sug.uploader || sug.channel, duration: sug.duration,
      thumb: sug.thumb || sug.thumbnail, thumbnail: sug.thumb || sug.thumbnail,
      source: sug.source || 'yt', provider: sug.provider || sug.source }, qRef.current);
  };

  // Bouton « Ajouter » : envoie TOUJOURS le texte tapé (jamais une suggestion)
  const submitTyped = () => {
    const text = q.trim();
    if (!text || busyRef.current) return;
    // Un titre tapé : la prochaine ligne du Roi ; un lien vidéo : cette vidéo. Une playlist n'a pas de Sceau.
    if (kind === 'none' || kind === 'video') expectSeal(kind === 'video' ? text : null, null, null);
    submit({ query: text }, q);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (busyRef.current) return;
      // Suggestion seulement si choisie au clavier (flèches) dans la liste ouverte
      if (enterPicksSuggestion(open, idx, sugs.length, q) && sugs[idx]) pick(sugs[idx], document.getElementById(optId(idx))?.querySelector('.th'));
      else submitTyped();
      return;
    }
    if (!open) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(sugs.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(-1, i - 1)); }
    else if (e.key === 'Escape') { setOpen(false); setIdx(-1); }
  };

  const shown = open && sugs.length > 0;
  const listed = sugs.length ? sugs : lastSugs.current;
  const submitKey = submitLabelKey(kind);
  const pill = pillText(kind);
  const inputId = `${uid}-q`, listId = `${uid}-sug`, optId = (i: number) => `${uid}-sug-${i}`;

  return (
    <div className="search">
      <label className="sr" htmlFor={inputId}>{t('search.srLabel')}</label>
      <div className="field" data-searching={searching} data-has-text={!!q.trim()}
        data-link={kind === 'none' ? undefined : kind}>
        <span className="ico-search" aria-hidden="true">
          <svg className="ico" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.2"/><path d="M15.5 15.5l4.5 4.5"/></svg>
          <span className="spin-ring"/>
        </span>
        <input ref={inputRef} id={inputId} type="text" autoComplete="off" spellCheck={false}
          value={q} onChange={e => onInput(e.target.value)}
          onFocus={() => sugs.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          onKeyDown={onKey}
          placeholder={t(narrow ? 'search.placeholderShort' : 'search.placeholder')}
          role="combobox" aria-expanded={shown} aria-controls={listId} aria-autocomplete="list"
          aria-activedescendant={shown && idx >= 0 ? optId(idx) : undefined}/>
        <span className="linkpill" data-kind={isBadLink(kind) ? 'bad' : 'ok'} aria-live="polite" title={pill || undefined}>
          {pill}
        </span>
        <span className="kbd" aria-hidden="true">/</span>
        {/* Pendant l'ajout, le libellé s'efface derrière la roue : le nom accessible dit « Ajout… » */}
        <button type="button" className="btn-add" onClick={submitTyped} disabled={busy || !q.trim()}
          data-loading={busy} aria-busy={busy} aria-label={busy ? t('search.submit.busy') : undefined}>
          <span className="lbls">
            {SUBMIT_KEYS.map(k => <span key={k} data-on={k === submitKey} aria-hidden={k !== submitKey}>{t(k)}</span>)}
          </span>
          <span className="spin" aria-hidden="true"/>
        </button>
      </div>
      {/* Survol : surlignage CSS (:hover) uniquement, il ne change pas la sélection clavier */}
      <div className="sug plaque" id={listId} role="listbox" aria-label={t('search.suggestionsTitle')}
        data-open={shown} onMouseLeave={() => setIdx(-1)}>
        <div className="sug-head" aria-hidden="true"><span>{t('search.suggestionsTitle')}</span></div>
        {listed.map((s, i) => {
          const thumb = s.thumb || s.thumbnail;
          return (
            <div key={`${s.url}-${i}`} id={optId(i)} role="option" aria-selected={i === idx} className="sug-item"
              onMouseDown={e => e.preventDefault()} onClick={(e) => pick(s, e.currentTarget.querySelector('.th'))}>
              <div className="th">
                {thumb ? <img src={thumb} alt="" width={64} height={36} loading="lazy" decoding="async"/>
                  : <svg viewBox="0 0 24 24" aria-hidden="true">{I.music}</svg>}
              </div>
              <div className="min-w-0">
                <div className="t">{s.title}</div>
                <div className="a">{s.artist || s.uploader || s.channel || ''}</div>
              </div>
              <span className="d tnum">{s.duration != null ? fmt(s.duration) : ''}</span>
            </div>
          );
        })}
        <div className="sug-foot" aria-hidden="true">{t('search.suggestionsHint')}</div>
      </div>
    </div>
  );
}
