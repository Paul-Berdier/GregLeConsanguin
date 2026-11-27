// Aide des tests d'appels à l'API (pas un fichier de test) : `fetch` remplacé le temps de `fn`, chaque appel noté.
export async function capture(fn, reply = { ok: true }, status = 200) {
  const realFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    const u = new URL(String(url));
    calls.push({ path: u.pathname, query: u.searchParams.toString(), method: opts.method,
      body: opts.body ? JSON.parse(opts.body) : undefined, credentials: opts.credentials });
    return new Response(JSON.stringify(reply), { status, headers: { 'content-type': 'application/json' } });
  };
  try { return { calls, res: await fn() }; } finally { globalThis.fetch = realFetch; }
}
