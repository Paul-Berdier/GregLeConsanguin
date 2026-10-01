/**
 * Polices « Nuit gothique », auto-hébergées (OFL, voir public/licenses/).
 * Chaque famille expose une variable CSS, reprise par les rôles --f-* de
 * tokens.css. Les chemins sont relatifs à ce fichier (exigence de next/font/local).
 */
import localFont from 'next/font/local';

// Titres d'apparat : wordmark, titres de panneaux, titres de nuit.
const grenzeGotisch = localFont({
  src: '../../public/fonts/GrenzeGotisch-VF.woff2',
  weight: '100 900',
  style: 'normal',
  variable: '--font-grenze-gotisch',
  adjustFontFallback: 'Times New Roman',
});

// Titre du morceau en cours.
const grenze = localFont({
  src: '../../public/fonts/Grenze-VF.woff2',
  weight: '100 900',
  style: 'normal',
  variable: '--font-grenze',
  adjustFontFallback: 'Times New Roman',
});

// Interface : tout ce qu'on lit ou clique.
const alegreyaSans = localFont({
  src: [
    { path: '../../public/fonts/AlegreyaSans-Regular.woff2', weight: '400', style: 'normal' },
    { path: '../../public/fonts/AlegreyaSans-Medium.woff2', weight: '500', style: 'normal' },
    { path: '../../public/fonts/AlegreyaSans-Bold.woff2', weight: '700', style: 'normal' },
    { path: '../../public/fonts/AlegreyaSans-ExtraBold.woff2', weight: '800', style: 'normal' },
  ],
  variable: '--font-alegreya-sans',
});

// Voix de Greg (répliques seulement, jamais au premier affichage) : pas de préchargement.
const alegreyaItalic = localFont({
  src: '../../public/fonts/Alegreya-Italic-VF.woff2',
  weight: '400 900',
  style: 'italic',
  variable: '--font-alegreya-italic',
  adjustFontFallback: 'Times New Roman',
  preload: false,
});

/** Classes à poser sur <html> : elles définissent les variables --font-*. */
export const fontVariables: string = [grenzeGotisch, grenze, alegreyaSans, alegreyaItalic]
  .map((f) => f.variable)
  .join(' ');
