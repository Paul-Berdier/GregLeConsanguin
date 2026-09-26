// Chargement des modules .ts de src/ pour les tests node:test (pas un fichier de test).
// - Node >= 22.18 / 23.6 : type stripping natif (aucune dépendance).
// - Sinon (ex. image Docker node:20) : transpilation via `typescript` (devDependency,
//   présente après `npm install`). GREG_TEST_TRANSPILE=1 force ce chemin.
// Les modules chargés ne doivent avoir AUCUN import runtime (seulement `import type`).
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export async function loadTs(relPath) {
  const url = new URL(relPath, import.meta.url);
  if (process.features?.typescript && !process.env.GREG_TEST_TRANSPILE) {
    return import(url.href);
  }
  let ts;
  try {
    ts = (await import('typescript')).default;
  } catch {
    throw new Error(
      `Node ${process.version} ne charge pas les .ts nativement : lancer \`npm install\` `
      + '(typescript) ou utiliser Node >= 22.18.',
    );
  }
  const src = await readFile(url, 'utf8');
  const out = ts.transpileModule(src, {
    fileName: fileURLToPath(url),
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(out.outputText).toString('base64')}`);
}
