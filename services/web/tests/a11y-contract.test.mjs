// Régions live (étape 4) : speak() écrit dans les deux régions persistantes du Héraut.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_contract.mjs';

test('speak() passe par les régions aria-live du Héraut (polie ou assertive)', () => {
  assert.match(read('src/components/Herald/store.ts'), /export function speak\(text: string, o: \{ assertive\?: boolean \} = \{\}\): void/);
  const herald = read('src/components/Herald/Herald.tsx');
  assert.match(herald, /setSpeaker\(\(text, assertive\) => write\(assertive \? alertRef\.current : politeRef\.current, text\)\)/);
  assert.match(herald, /return \(\) => \{ setAnnouncer\(null\); setSpeaker\(null\); \};/);
});
