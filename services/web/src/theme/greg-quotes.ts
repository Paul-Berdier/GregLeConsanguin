export const GREG_QUOTES = [
  "Je suis pas grognon, je suis en mode économie d'empathie.",
  "On m'a invoqué pour des goûts douteux. Mission acceptée.",
  "Je suis comme un vin millésimé : acide, mais inévitable.",
  "Votre silence était une amélioration notable. Dommage.",
  "Moi vivant, vous n'aurez jamais le silence que vous méritez.",
  "Le silence est d'or. L'or, contrairement à moi, a de la valeur.",
  "Avant j'étais noble. Maintenant je mets du YouTube dans des vocaux Discord.",
  "Ma noblesse est déchue, mais mon mépris est intact.",
  "Servir des manants, c'est mon destin. Le vôtre c'est d'écouter.",
  "Je suis payé en mépris, et croyez-moi, le salaire est généreux.",
];

export function randomQuote(): string {
  return GREG_QUOTES[Math.floor(Math.random() * GREG_QUOTES.length)];
}
