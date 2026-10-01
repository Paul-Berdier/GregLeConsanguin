/**
 * FLIP d'une boîte de la scène quand R change avec elle (jour → nuit, Stage.tsx) : le portail et la lumière gardent
 * leur boîte du jour pendant leur fondu, comme la rose (écart 10 de l'étape 2). Pur, sans import runtime
 * (tests/stage-motion.test.mjs).
 */

/** Boîte dans le repère de la rose : x, son centre depuis le milieu de la scène ; y, son haut depuis le haut de la scène. */
export type StageBox = { x: number; y: number; w: number; h: number };
export type Flip = { x: number; y: number; sx: number; sy: number };

/** Ce qui ramène `to` sur `from`, origine de transformation au centre (celle du portail et de la lumière). */
export function flipBox(from: StageBox, to: StageBox): Flip {
  return { x: from.x - to.x, y: from.y + from.h / 2 - (to.y + to.h / 2), sx: from.w / to.w, sy: from.h / to.h };
}

/**
 * Images clés en translate et scale, pas en transform : un transform animé remplacerait la transition CSS du portail
 * (transform → scale(.97), portal.css) au lieu de s'y ajouter ; translate et scale se composent avec elle (vu dans Chrome).
 */
export function flipFrames(f: Flip): Keyframe[] {
  return [{ translate: `${f.x}px ${f.y}px`, scale: `${f.sx} ${f.sy}` }, { translate: '0px 0px', scale: '1' }];
}
