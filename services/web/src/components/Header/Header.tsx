'use client';

import { useEffect, useRef } from 'react';
import { usePlayer } from '@/hooks/usePlayer';
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
 * Déconnecté, la nuit de la scène porte le seul « Se connecter avec Discord » (NightState ; prototype :
 * « the hero carries the only CTA », DESIGN §10) : l'en-tête n'a alors ni bouton de connexion ni recherche.
 * `ready` : la session a été vérifiée (boot) ; avant, rien ne disparaît ni ne clignote.
 */
export default function Header({ ready = true }: { ready?: boolean }) {
  const { me } = usePlayer();
  const wasIn = useRef(false);

  // Déconnexion : le compte disparaît avec le focus, qui retomberait sur <body>. On le passe
  // au « Se connecter » de la scène, sans le voler s'il est déjà ailleurs.
  useEffect(() => {
    if (me) { wasIn.current = true; return; }
    const lost = !document.activeElement || document.activeElement === document.body;
    if (wasIn.current && lost) document.querySelector<HTMLElement>('.night[data-kind="out"] .btn-solid')?.focus();
    wasIn.current = false;
  }, [me]);

  return (
    <header className="top" data-auth={ready && !me ? 'out' : undefined}>
      <div className="brand">
        <GregMedal/>
        <span className="sr">{t('brand.name')}</span>
        <Wordmark/>
      </div>

      <SearchBar/>

      <div className="top-right">
        {me && (
          <>
            <GuildPicker/>
            <AccountMenu/>
          </>
        )}
      </div>
    </header>
  );
}
