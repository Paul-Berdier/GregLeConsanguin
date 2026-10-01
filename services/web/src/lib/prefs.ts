/**
 * Réglage « Répliques de Greg » (menu du compte), pur (tests/prefs.test.mjs) : 'off' les coupe (faits seulement),
 * absent ou 'on' les garde. Reflété sur <html data-quips> : les feuilles cachent les répliques sous data-quips=off.
 */
export const QUIPS_STORAGE_KEY = 'greg.webplayer.quips';
export const quipsOn = (stored: string | null | undefined): boolean => stored !== 'off';

/**
 * Script du <head> (layout.tsx) : pose <html data-quips> avant la première peinture, que le Roi soit connu ou non
 * (nuit de chargement, nuit « déconnecté » : le menu du compte n'y est pas monté). Le menu ne fait que basculer.
 */
export const QUIPS_SCRIPT = `try{document.documentElement.dataset.quips=localStorage.getItem(${JSON.stringify(QUIPS_STORAGE_KEY)})==='off'?'off':'on'}catch(e){document.documentElement.dataset.quips='on'}`;
