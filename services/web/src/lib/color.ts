/**
 * Couleurs : conversion hex → RVB et contraste WCAG 2.x (aucun import runtime).
 * Sert à vérifier les tokens « Nuit gothique ». Voir tests/color.test.mjs.
 */
export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  const v = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16)) as [number, number, number];
}

// Luminance relative WCAG 2.x (seuil sRGB 0.03928, comme la norme).
export function relLuminance([r, g, b]: [number, number, number]): number {
  const f = (c: number) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

// Rapport de contraste (1 à 21), indépendant de l'ordre des deux couleurs.
export function contrast(a: string, b: string): number {
  const [la, lb] = [relLuminance(hexToRgb(a)), relLuminance(hexToRgb(b))].sort((x, y) => y - x);
  return (la + 0.05) / (lb + 0.05);
}
