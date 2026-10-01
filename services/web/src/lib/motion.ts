/**
 * Jetons de mouvement pour l'API Web Animations (motion.md §4.2). Mêmes valeurs que les variables de
 * src/theme/tokens.css (motion.md §4.1) : tests/motion.test.mjs le vérifie.
 * Pur, sans import runtime.
 */

export const DUR = {
  press: 120, hover: 150, micro: 160, popIn: 200, popOut: 120, shift: 200, exit: 180, enter: 260,
  text: 280, toast: 400, reveal: 420, flight: 420, glint: 900, ambient: 900, stagger: 30,
} as const;

export const EASE = {
  out: 'cubic-bezier(.23,1,.32,1)',
  inOut: 'cubic-bezier(.77,0,.175,1)',
  drawer: 'cubic-bezier(.32,.72,0,1)',
  shift: 'cubic-bezier(.2,0,0,1)',
  drop: 'cubic-bezier(.2,1,.1,1)',
  flash: 'cubic-bezier(.25,.1,.25,1)',
} as const;

export const SPRING = {
  snap: { dur: 450, easing: 'linear(0,.1787,.4522,.668,.8096,.8947,.9432,.97,.9843,.9919,.9959,.9979,.999,.9995,1)' },
  move: { dur: 650, easing: 'linear(0,.0792,.2371,.4044,.5525,.6726,.7652,.8341,.8842,.9199,.9451,.9626,.9747,.9829,.9886,.9924,.9949,.9966,.9978,.9985,.999,1)' },
  settle: { dur: 750, easing: 'linear(0,.0663,.2105,.3763,.5332,.6669,.7733,.8533,.9107,.9499,.9754,.9911,1,1.0044,1.0061,1.0062,1.0055,1.0045,1.0035,1.0026,1.0018,1.0012,1.0008,1,1)' },
  seal: { dur: 700, easing: 'linear(0,.0581,.1953,.3667,.5407,.6976,.8271,.9258,.9947,1.0379,1.0605,1.0679,1.0652,1.0566,1.0451,1.0332,1.0222,1.0131,1.006,1.001,.9978,.9961,1)' },
} as const;
export type SpringName = keyof typeof SPRING;

/** Courbe de repli d'un ressort quand le moteur ne lit pas linear() : sans rebond, la même arrivée douce. */
const SPRING_FALLBACK: Record<SpringName, string> = { snap: EASE.out, move: EASE.out, settle: EASE.out, seal: EASE.drop };

let linearOk: boolean | undefined;
/**
 * linear() lisible ? (Chrome 113, Firefox 112, Safari 17.2.) Sinon animate() lève une TypeError (iOS 16, Safari 17.1),
 * dans un effet de mise en page : toute l'app tomberait. Lu une fois ; faux sans CSS.supports (rendu serveur, Node).
 */
export function linearEasingOk(): boolean {
  if (linearOk === undefined) {
    linearOk = typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('transition-timing-function', 'linear(0, 1)');
  }
  return linearOk;
}

/** Courbe d'un ressort pour animate() : SPRING[name].easing si le moteur lit linear(), sinon une cubic-bezier. */
export function springEasing(name: SpringName, linear: boolean = linearEasingOk()): string {
  return linear ? SPRING[name].easing : SPRING_FALLBACK[name];
}

/** Éclair après un déplacement (Atlassian) et secousse d'un refus (motion.md §6.8). */
export const FLASH_MS = 700;
export const SHAKE_MS = 320;
export const SHAKE_X = [0, -4, 4, -3, 2, 0] as const;
/** Cascade d'entrée plafonnée à 8 lignes. */
export const STAGGER_CAP = 8;

/** Mouvement réduit demandé par le système (relu à chaque appel : le réglage peut changer en direct). */
export function reducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Suit prefers-reduced-motion en direct (DESIGN §12.6) : `fn` tout de suite, puis à chaque changement. */
export function watchReducedMotion(fn: (reduced: boolean) => void): () => void {
  if (typeof matchMedia !== 'function') { fn(false); return () => {}; }
  const mq = matchMedia('(prefers-reduced-motion: reduce)');
  const on = (): void => fn(mq.matches);
  on();
  mq.addEventListener('change', on);
  return () => mq.removeEventListener('change', on);
}
