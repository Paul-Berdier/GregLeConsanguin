import { has, t } from '@/theme/copy';

// Portrait de Greg (Charles II par Carreño de Miranda, domaine public) : celui d'un valet, sans couronne.
const TIP = has('brand.medalTip') ? t('brand.medalTip') : 'Greg, votre valet';

/** Médaillon de l'en-tête. Décoratif : le nom est donné à côté (texte masqué de la marque). */
export default function GregMedal() {
  return (
    <span className="medal" title={TIP} aria-hidden="true">
      <img src="/gothique/greg-face-96.webp" srcSet="/gothique/greg-face-96.webp 1x, /gothique/greg-face-192.webp 2x"
        alt="" width={38} height={38} decoding="async"/>
    </span>
  );
}
