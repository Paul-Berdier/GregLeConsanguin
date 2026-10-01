/**
 * Worker de la rosace (module worker, créé par client.ts avec `new Worker(new URL(...), import.meta.url)`).
 * Il lit la pierre et la miniature, extrait la palette, peint la fenêtre sur OffscreenCanvas et renvoie
 * des ImageBitmap transférées : le fil principal ne fait qu'échanger des canevas.
 * Protocole repris de proto-gothique/work/refine/rose-worker.js (lignes 496–514).
 */
import { paintWindow } from './paint';
import type { PaintOutput } from './paint';
import { GRISAILLE, MOONLIGHT, SAMPLE_H, SAMPLE_W, paletteFromPixels, thumbUrl } from './palette';
import type { Palette, PaletteMode, RGB } from './palette';

export type RoseIn =
  | { type: 'init'; stoneUrl: string }
  | { type: 'paint'; key: string; id: string | null; R: number; dpr: number; ringTo: number };
export type RoseOut =
  | ({ type: 'painted'; key: string; pal: { mode: PaletteMode; lum: RGB }; ms: [number, number] } & PaintOutput)
  | { type: 'failed'; key: string; error: string };

// Le lib TS du projet est « dom » : on type à la main la portée du worker.
type Scope = { onmessage: ((e: MessageEvent<RoseIn>) => void) | null; postMessage(m: RoseOut, transfer?: Transferable[]): void };
const scope = self as unknown as Scope;

let stone: Promise<ImageBitmap | null> = Promise.resolve(null);
const palettes = new Map<string, Palette>();

async function loadStone(url: string): Promise<ImageBitmap | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await createImageBitmap(await res.blob());
  } catch { return null; }
}

/**
 * Milieu 16:9 de hqdefault (4:3 à bandes noires) réduit à 48 × 27, puis histogramme des teintes.
 * null : miniature injoignable (réseau, réponse en erreur, image illisible), à retenter plus tard.
 */
async function extractPalette(id: string): Promise<Palette | null> {
  try {
    const res = await fetch(thumbUrl(id), { mode: 'cors' });
    if (!res.ok) return null;
    const bm = await createImageBitmap(await res.blob());
    const c = new OffscreenCanvas(SAMPLE_W, SAMPLE_H);
    const x = c.getContext('2d', { willReadFrequently: true });
    if (!x) { bm.close(); return GRISAILLE; }
    x.drawImage(bm, 0, bm.height * 0.125, bm.width, bm.height * 0.75, 0, 0, SAMPLE_W, SAMPLE_H);
    bm.close();
    return paletteFromPixels(x.getImageData(0, 0, SAMPLE_W, SAMPLE_H).data);
  } catch { return null; }
}

scope.onmessage = async (e) => {
  const m = e.data;
  if (m.type === 'init') { stone = loadStone(m.stoneUrl); return; }
  try {
    const t0 = performance.now();
    let pal: Palette;
    if (!m.id) pal = MOONLIGHT;
    else {
      const known = palettes.get(m.id);
      const got = known ?? (await extractPalette(m.id));
      // un échec passager se peint en grisaille sans être retenu : la couleur reviendra à la prochaine peinture
      pal = got ?? GRISAILLE;
      if (!known && got) {
        palettes.set(m.id, got);
        if (palettes.size > 64) palettes.delete(palettes.keys().next().value as string);
      }
    }
    const t1 = performance.now();
    const out = paintWindow({ R: m.R, dpr: m.dpr, pal, stone: await stone, ringTo: m.ringTo });
    const transfer: Transferable[] = [out.win, out.bloom];
    if (out.ring && out.head) transfer.push(out.ring, out.head);
    scope.postMessage({ type: 'painted', key: m.key, pal: { mode: pal.mode, lum: pal.lum }, ...out, ms: [Math.round(t1 - t0), Math.round(performance.now() - t1)] }, transfer);
  } catch (err) {
    scope.postMessage({ type: 'failed', key: m.key, error: String(err) });
  }
};
