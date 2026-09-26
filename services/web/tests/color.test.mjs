import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './_loadTs.mjs';
const { contrast, hexToRgb } = await loadTs('../src/lib/color.ts');
test('hexToRgb', () => { assert.deepEqual(hexToRgb('#0b0908'), [11, 9, 8]); });
test('contrastes des tokens de texte (DESIGN §2)', () => {
  const nef = '#14110e';
  assert.ok(contrast('#efe7d8', nef) >= 15.0, 'os/nef');
  assert.ok(contrast('#9b9183', nef) >= 6.0, 'cendre/nef');
  assert.ok(contrast('#cfa75a', nef) >= 8.0, 'or/nef');
  assert.ok(contrast('#e0583e', nef) >= 5.0, 'gueules/nef');
  assert.ok(contrast('#9b9183', '#27221c') >= 4.5, 'cendre/voute-2');
});
