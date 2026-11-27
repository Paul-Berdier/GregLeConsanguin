'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { usePopover } from '@/components/Header/GuildPicker';
import { api } from '@/lib/api';
import {
  ageMinutes, browserSession, deviceErrorKey, formatUserCode, meFailureView, normalizeUserCode, pickDeviceGuild,
  savePendingCode, takePendingCode,
} from '@/lib/devices';
import type { DeviceGuild, DeviceToken } from '@/lib/devices';
import { t } from '@/theme/copy';
import { tx } from '@/theme/copy.extra';

/** Ce que lookup dit d'une demande : le nom que l'appli s'est donné et l'heure de la demande (secondes epoch). */
type Found = { code: string; name: string; createdAt: number };
/** Réponse de lookup pour un code : la demande, ou la clé du texte d'erreur. */
type Lookup = { code: string; found: Found | null; err: string | null };

/** « Autoriser » reste inerte ce temps après l'affichage de l'appareil, puis à chaque retour sur la fenêtre (focus,
 * onglet de nouveau visible) : un double-clic piégé (une fenêtre surgissante qui s'efface sous le curseur) ne
 * tombe jamais sur lui. frame-ancestors (next.config.js) ne pare que l'encadrement. */
const ARMEMENT_MS = 1000;

function savedGuild(): string | null {
  try { return localStorage.getItem('greg.webplayer.guild_id'); } catch { return null; }
}

/** Secondes epoch → date du jour, à la française. */
function day(s: number): string {
  return new Date(s * 1000).toLocaleDateString('fr-FR');
}

/** Un appareil lié et son « Délier », confirmé comme « Tout arrêter » (Transport.tsx) : le focus va sur « Garder ». */
function TokenRow({ token, onUnlink }: { token: DeviceToken; onUnlink: (token: DeviceToken) => void }) {
  const confirm = usePopover();
  const noRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  useEffect(() => { if (confirm.open) noRef.current?.focus(); }, [confirm.open]);

  return (
    <li className="lier-token">
      <div className="lier-token-text">
        <b>{token.label}</b>
        <span className="vl-small">{tx('devices.lastUsed', { date: day(token.last_used_at) })}</span>
        <span className="vl-small">{tx('devices.expires', { date: day(token.expires_at) })}</span>
      </div>
      <div className="lier-unlink" {...confirm.wrapProps}>
        <button ref={confirm.btnRef} type="button" className="btn-ghost" aria-haspopup="dialog" aria-expanded={confirm.open}
          onClick={() => confirm.setOpen((o) => !o)}>
          {tx('devices.unlink')}
        </button>
        <div className="pop plaque confirm" role="dialog" aria-labelledby={titleId} aria-describedby={bodyId} data-open={confirm.open}>
          <h3 id={titleId}>{tx('devices.confirm.title', { name: token.label })}</h3>
          <p id={bodyId}>{tx('devices.confirm.body')}</p>
          <div className="row-btns">
            <button ref={noRef} type="button" className="btn-ghost" onClick={() => confirm.close(true)}>{tx('devices.confirm.no')}</button>
            <button type="button" className="btn-danger" onClick={() => { confirm.close(true); onUnlink(token); }}>
              {tx('devices.confirm.yes')}
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}

/**
 * /lier (spec 2026-11-25 §5) : tout compte connecté y autorise le code de l'appli Greg pour lui-même, et y délie ses
 * appareils. Sans lecteur ni socket. Non connecté (401 de /users/me seulement) : « Se connecter avec Discord », le code
 * de l'URL gardé pour le retour (boot() de « / » renvoie ici) ; une autre panne propose « Réessayer ». Rien n'est
 * autorisé sans un clic. Styles : components/Lier/lier.css.
 */
export default function LierPage() {
  const [view, setView] = useState<'loading' | 'out' | 'in' | 'error'>('loading');
  const [bootTry, setBootTry] = useState(0);
  const [retry, setRetry] = useState(0);
  const [loginCode, setLoginCode] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [guilds, setGuilds] = useState<DeviceGuild[] | null>(null);
  const [guildsErr, setGuildsErr] = useState<string | null>(null);
  const [guildId, setGuildId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<'approve' | 'deny' | null>(null);
  const [decideErr, setDecideErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tokens, setTokens] = useState<DeviceToken[] | null>(null);
  const [tokensErr, setTokensErr] = useState<string | null>(null);
  const [unlinkErr, setUnlinkErr] = useState<string | null>(null);
  const [unlinked, setUnlinked] = useState('');
  const [armed, setArmed] = useState(false);
  const busyRef = useRef(false);
  const armedRef = useRef(false);
  const revoking = useRef(new Set<string>());
  const doneRef = useRef<HTMLParagraphElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLHeadingElement>(null);
  const codeId = useId();
  const guildSelId = useId();
  const listId = useId();

  useEffect(() => {
    const urlCode = normalizeUserCode(new URLSearchParams(window.location.search).get('code'));
    let alive = true;
    (async () => {
      try {
        const me = await api.getMe();
        if (!me || typeof me !== 'object') throw new Error('/users/me illisible');
      } catch (e) {
        if (!alive) return;
        // Seul un 401 veut dire « non connecté » ; une panne (5xx, réseau, réponse illisible) se réessaie.
        if (meFailureView(e) === 'out') {
          setLoginCode(urlCode);
          setView('out');
        } else {
          setView('error');
        }
        return;
      }
      if (!alive) return;
      // Connecté : le code en attente est pris tout de suite, avant /overlay/* ; même si l'un d'eux échoue,
      // « / » ne renverra plus ici.
      const pending = takePendingCode(browserSession(), Date.now());
      const prefill = urlCode ?? pending;
      if (prefill) setInput(formatUserCode(prefill));
      setView('in');
      window.history.replaceState(null, '', '/lier');
      api.deviceGuilds().then((r) => {
        if (!alive) return;
        const list: DeviceGuild[] = Array.isArray(r?.guilds) ? r.guilds : [];
        setGuilds(list);
        setGuildId(pickDeviceGuild(list, savedGuild()));
      }, (e) => { if (alive) setGuildsErr(deviceErrorKey(e)); });
      api.deviceTokens().then((r) => {
        if (alive) setTokens(Array.isArray(r?.tokens) ? r.tokens : []);
      }, (e) => { if (alive) setTokensErr(deviceErrorKey(e)); });
    })();
    return () => { alive = false; };
  }, [bootTry]);

  // Code complet : on montre l'appareil qui le demande (lecture seule) ; l'autorisation attend le clic du Roi.
  // `retry` relance la consultation du même code après une panne.
  const code = view === 'in' ? normalizeUserCode(input) : null;
  useEffect(() => {
    if (!code) return;
    let alive = true;
    api.deviceLookup(code).then((r) => {
      if (alive) setLookup({ code, found: { code, name: String(r?.client_name ?? ''), createdAt: Number(r?.created_at) }, err: null });
    }, (e) => { if (alive) setLookup({ code, found: null, err: deviceErrorKey(e) }); });
    return () => { alive = false; };
  }, [code, retry]);
  const shown = code && lookup?.code === code ? lookup : null;
  const found = shown?.found ?? null;
  // 8 lettres ou plus qui ne font pas un code (voyelle, chiffre, une de trop) : on le dit, plutôt que rien
  const badCode = !code && input.replace(/[^\p{L}\p{N}]/gu, '').length >= 8;

  // Armement de « Autoriser » : le délai part de l'affichage de l'appareil et repart de zéro à chaque retour sur
  // la fenêtre. Le ref sert au clic (lu sans attendre un rendu), l'état à aria-disabled.
  const foundCode = found?.code ?? null;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const disarm = () => { armedRef.current = false; setArmed(false); clearTimeout(timer); };
    disarm();
    if (!foundCode) return;
    const arm = () => {
      disarm();
      timer = setTimeout(() => { armedRef.current = true; setArmed(true); }, ARMEMENT_MS);
    };
    const onVisibility = () => { if (document.visibilityState === 'visible') arm(); };
    arm();
    window.addEventListener('focus', arm);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      clearTimeout(timer);
      armedRef.current = false;
      window.removeEventListener('focus', arm);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [foundCode]);

  useEffect(() => { if (outcome) doneRef.current?.focus(); }, [outcome]);

  async function decide(decision: 'approve' | 'deny') {
    if (!found || busyRef.current) return;
    if (decision === 'approve' && !armedRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setDecideErr(null);
    try {
      await api.deviceDecide(found.code, decision, decision === 'approve' ? guildId ?? undefined : undefined);
      setOutcome(decision);
      setInput('');
      setLookup(null);
    } catch (e) {
      setDecideErr(deviceErrorKey(e));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function unlink(token: DeviceToken) {
    if (revoking.current.has(token.id)) return;
    revoking.current.add(token.id);
    setUnlinkErr(null);
    try {
      await api.deviceRevoke(token.id);
      setTokens((list) => list && list.filter((x) => x.id !== token.id));
      setUnlinked(tx('devices.unlinked', { name: token.label }));
      listRef.current?.focus();   // la ligne et son bouton disparaissent
    } catch (e) {
      setUnlinkErr(deviceErrorKey(e));
    } finally {
      revoking.current.delete(token.id);
    }
  }

  if (view === 'loading') {
    return (
      <main className="lier">
        <section className="lier-card plaque" aria-busy="true">
          <p className="vl-kicker">{tx('devices.kicker')}</p>
          <h1 className="vl-title">{tx('devices.title')}</h1>
          <p className="vl-body" role="status">{t('loading.boot.text')}</p>
        </section>
      </main>
    );
  }

  if (view === 'error') {
    return (
      <main className="lier">
        <section className="lier-card plaque">
          <p className="vl-kicker">{tx('devices.kicker')}</p>
          <h1 className="vl-title">{tx('devices.title')}</h1>
          <p className="lier-alert" role="alert">{tx('devices.error.generic')}</p>
          <button type="button" className="btn-solid" onClick={() => { setView('loading'); setBootTry((n) => n + 1); }}>
            {tx('devices.retry')}
          </button>
        </section>
      </main>
    );
  }

  if (view === 'out') {
    return (
      <main className="lier">
        <section className="lier-card plaque">
          <p className="vl-kicker">{tx('devices.kicker')}</p>
          <h1 className="vl-title">{tx('devices.title')}</h1>
          <p className="vl-body">{loginCode ? tx('devices.loginWithCode', { code: formatUserCode(loginCode) }) : tx('devices.login')}</p>
          <a className="btn-solid" href={api.getLoginUrl()}
            onClick={() => { if (loginCode) savePendingCode(browserSession(), loginCode, Date.now()); }}>
            {t('auth.cta')}
          </a>
          <p className="vl-small">{t('auth.privacy')}</p>
        </section>
      </main>
    );
  }

  const age = found ? ageMinutes(found.createdAt, Date.now()) : 0;
  // Session finie pendant la page : se reconnecter, le code en cours gardé pour le retour (boot() de « / » renvoie ici).
  const relogin = (
    <a className="btn-ghost" href={api.getLoginUrl()}
      onClick={() => { if (code) savePendingCode(browserSession(), code, Date.now()); }}>
      {t('auth.cta')}
    </a>
  );

  return (
    <main className="lier">
      <section className="lier-card plaque">
        <p className="vl-kicker">{tx('devices.kicker')}</p>
        <h1 className="vl-title">{tx('devices.title')}</h1>
        <p className="vl-body">{tx('devices.intro')}</p>

        <label className="lier-label" htmlFor={codeId}>{tx('devices.codeLabel')}</label>
        <div className="field">
          <input ref={inputRef} id={codeId} value={input} autoComplete="off" autoCapitalize="characters" autoCorrect="off" spellCheck={false}
            aria-invalid={badCode || undefined}
            onChange={(e) => { setInput(e.target.value); setOutcome(null); setDecideErr(null); }}/>
        </div>
        {badCode && <p className="lier-alert" role="alert">{tx('devices.error.INVALID_CODE')}</p>}
        {shown?.err && <p className="lier-alert" role="alert">{tx(shown.err)}</p>}
        {/* le bouton disparaît pendant la nouvelle consultation : le focus va au champ du code */}
        {shown?.err === 'devices.error.generic' && (
          <button type="button" className="btn-ghost" onClick={() => { setLookup(null); setRetry((n) => n + 1); inputRef.current?.focus(); }}>
            {tx('devices.retry')}
          </button>
        )}
        {shown?.err === 'devices.error.SESSION' && relogin}

        {found && (
          <div className="lier-device">
            <p className="lier-name">{tx('devices.device', { name: found.name })}</p>
            <p className="vl-small">{age === 0 ? tx('devices.ageNow') : tx('devices.age', { n: age })}</p>
            <p className="lier-warning">{tx('devices.warning')}</p>

            {guildsErr || guilds?.length === 0 ? (
              <>
                <p className="lier-label">{tx('devices.guildLabel')}</p>
                {guildsErr ? <p className="lier-alert" role="alert">{tx(guildsErr)}</p> : <p className="vl-small">{tx('devices.guildNone')}</p>}
              </>
            ) : (
              <>
                <label className="lier-label" htmlFor={guildSelId}>{tx('devices.guildLabel')}</label>
                <div className="lier-select">
                  <select id={guildSelId} value={guildId ?? ''} disabled={!guilds} onChange={(e) => setGuildId(e.target.value)}>
                    {(guilds ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                  <svg className="ico" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M7 10l5 5 5-5"/></svg>
                </div>
              </>
            )}

            <div className="lier-actions">
              <button type="button" className="btn-solid" aria-disabled={busy || !armed} onClick={() => decide('approve')}>{tx('devices.approve')}</button>
              <button type="button" className="btn-ghost" aria-disabled={busy} onClick={() => decide('deny')}>{tx('devices.deny')}</button>
            </div>
            {decideErr && <p className="lier-alert" role="alert">{tx(decideErr)}</p>}
            {decideErr === 'devices.error.SESSION' && relogin}
          </div>
        )}
        {outcome && (
          <p ref={doneRef} className="lier-done" role="status" tabIndex={-1}>
            {outcome === 'approve' ? tx('devices.approved') : tx('devices.denied')}
          </p>
        )}

        <div className="lier-sep"/>

        <section aria-labelledby={listId}>
          <h2 ref={listRef} id={listId} className="lier-h2" tabIndex={-1}>{tx('devices.listTitle')}</h2>
          {tokensErr ? <p className="lier-alert" role="alert">{tx(tokensErr)}</p>
            : tokens === null ? <p className="vl-small" role="status">{t('loading.boot.text')}</p>
            : !tokens.length ? <p className="vl-small">{tx('devices.listEmpty')}</p>
            : (
              <ul className="lier-tokens">
                {tokens.map((tk) => <TokenRow key={tk.id} token={tk} onUnlink={unlink}/>)}
              </ul>
            )}
          {unlinkErr && <p className="lier-alert" role="alert">{tx(unlinkErr)}</p>}
          <p className="lier-note" role="status">{unlinked}</p>
        </section>

        <a className="btn-ghost" href="/">{tx('devices.back')}</a>
      </section>
    </main>
  );
}
