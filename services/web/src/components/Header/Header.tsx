'use client';

import { useEffect, useRef } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
import { api } from '@/lib/api';
import { t } from '@/theme/copy';
import GregMedal from './GregMedal';
import Wordmark from './Wordmark';
import SearchBar from './SearchBar';
import GuildPicker from './GuildPicker';
import AccountMenu from './AccountMenu';

/**
 * En-tête « Nuit gothique » : Greg (médaillon et wordmark, sans couronne), la recherche,
 * puis le serveur et le compte du Roi (avatar couronné). Styles : header.css.
 *
 * `ready` : la session a été vérifiée (boot). Avant, ni bouton de connexion ni compte :
 * pas de « Se connecter » qui clignote pour un Roi déjà connecté.
 */
export default function Header({ ready = true }: { ready?: boolean }) {
  const { me } = usePlayer();
  const loginRef = useRef<HTMLAnchorElement>(null);
  const wasIn = useRef(false);

  // Déconnexion : le compte disparaît avec le focus, qui retomberait sur <body>. On le passe
  // à « Se connecter », sans le voler s'il est déjà ailleurs.
  useEffect(() => {
    if (me) { wasIn.current = true; return; }
    const lost = !document.activeElement || document.activeElement === document.body;
    if (wasIn.current && lost) loginRef.current?.focus();
    wasIn.current = false;
  }, [me]);

  return (
    <header className="top">
      <div className="brand">
        <GregMedal/>
        <span className="sr">{t('brand.name')}</span>
        <Wordmark/>
      </div>

      <SearchBar/>

      <div className="top-right">
        {me ? (
          <>
            <GuildPicker/>
            <AccountMenu/>
          </>
        ) : ready ? (
          <a ref={loginRef} href={api.getLoginUrl()} className="btn-solid">{t('auth.cta')}</a>
        ) : null}
      </div>
    </header>
  );
}
