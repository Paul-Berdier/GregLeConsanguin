// La vidéo en plein écran, « La Grand-Salle » (conception du 2026-11-23, §2) : les invariants du balisage et des feuilles.
// Garde-fous sur le texte source, comme stage-contract : ils attrapent un retour en arrière évident (iframe déplacée,
// filtre sur la vidéo, raccourci rouvert, focus non piégé) ; le comportement se vérifie dans le navigateur.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { animated, read } from './_contract.mjs';
import { loadTs } from './_loadTs.mjs';
const { EXTRA, tx } = await loadTs('../src/theme/copy.extra.ts');
const F = await loadTs('../src/lib/stage/fullscreen.ts');

const noComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const code = (p) => read(p).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
/** Déclarations d'une règle dont le sélecteur est exactement `sel` (première occurrence). */
const ruleBody = (css, sel) => css.match(new RegExp(`(?:^|[\\n{}])\\s*${sel.replace(/[.[\]=()>:*]/g, '\\$&')}\\s*\\{([^}]*)\\}`))?.[1] ?? '';
const THEATER_CSS = 'src/components/Stage/theater.css';

test('feuille : importée avec la scène, transform et opacity seulement, mouvement réduit des deux façons', () => {
  const globals = read('src/app/globals.css');
  assert.ok(globals.includes("@import '../components/Stage/theater.css';"));
  assert.ok(globals.indexOf('theater.css') > globals.indexOf("Stage/portal.css'"), 'après portal.css : ses règles de plein écran l’emportent');
  const css = read(THEATER_CSS);
  for (const prop of animated(css)) assert.ok(['transform', 'opacity', 'none'].includes(prop), `theater.css : anime « ${prop} »`);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.th-ui[^}]*transition:\s*none/);
  assert.match(noComments(css), /:root\[data-motion=reduced\][^{]*\.th-ui[^{]*\{\s*transition:\s*none/);
});

test('translucide par la couleur seule : ni filter ni backdrop-filter autour de l’iframe', () => {
  // un seul filtre permis, « filter: none », qui en ôte un
  for (const [decl] of noComments(read(THEATER_CSS)).matchAll(/(?<![-\w])(?:backdrop-)?filter\s*:\s*[^;}]+/g)) {
    assert.match(decl, /^filter\s*:\s*none\s*$/, `theater.css : ${decl}`);
  }
  assert.doesNotMatch(noComments(read('src/components/Stage/portal.css')), /backdrop-filter/, 'portal.css');
  const css = noComments(read(THEATER_CSS));
  // le Transport de la scène monte dans la surcouche : chaque filtre que now.css pose sur ses boutons y est ôté
  const now = noComments(read('src/components/Stage/now.css'));
  const filtered = [...now.matchAll(/([^{}]*\.tbtn[^{}]*)\{[^}]*(?<![-\w])filter\s*:\s*(?!none)/g)].map(([, sel]) => sel.trim());
  for (const sel of filtered) assert.match(ruleBody(css, `.theater ${sel}`), /(?<![-\w])filter:\s*none/, `now.css : ${sel}`);
  assert.match(ruleBody(css, '.th-queue'), /background:\s*rgb\(11 9 8 \/ \.6\)/, 'plaque de la file');
  assert.match(ruleBody(css, '.th-queue'), /var\(--hair\)/, 'filet');
  assert.match(ruleBody(css, '.th-title'), /var\(--f-title\)/, 'titre en Grenze');
});

test('plein écran : fond noir, posters entiers ; la nuit n’éteint ni ne bloque la vidéo (API et repli)', () => {
  const css = noComments(read(THEATER_CSS));
  assert.match(ruleBody(css, '.video[data-fs] .poster'), /object-fit:\s*contain/);
  assert.match(ruleBody(css, '.video[data-fs]'), /pointer-events:\s*auto/, 'pointer-events: none du portail, hérité la nuit');
  const portal = ruleBody(css, '.stage[data-fs=pseudo] .portal');
  for (const re of [/opacity:\s*1/, /transform:\s*none/, /pointer-events:\s*auto/, /z-index:\s*\d{3}/]) assert.match(portal, re, `repli : ${re}`);
  const video = ruleBody(css, '.stage[data-fs=pseudo] .video');
  for (const re of [/position:\s*fixed/, /inset:\s*0/, /transform:\s*none/]) assert.match(video, re, `repli : ${re}`);
  // .stage[data-fs=pseudo] .video (0,3,0) passe après .stage[data-paused=true] .video (portal.css, même poids)
  assert.match(css, /\.stage-col:has\(> \.stage\[data-fs=pseudo\]\)\s*\{\s*container-type:\s*normal;?\s*\}/);
  assert.match(ruleBody(css, '.th-queue[hidden]'), /display:\s*none/, 'display: flex ne doit pas rouvrir la file masquée');
});

test('repli : ni bande de page à droite (gouttière), ni fantôme de vol par-dessus la surcouche', () => {
  const css = noComments(read(THEATER_CSS));
  // une colonne : stage.css garde une gouttière ; sans défilement (repli), elle laisserait la page voir à droite
  assert.match(noComments(read('src/components/Stage/stage.css')), /@media \(max-width: 900px\) \{\s*html \{ scrollbar-gutter: stable; \}/);
  assert.match(ruleBody(css, 'html:has(.stage[data-fs=pseudo])'), /scrollbar-gutter:\s*auto/);
  // les fantômes (fixes, dans <body>, z-index 80) passeraient au-dessus de la pile de .page-shell (10), donc de la vidéo
  assert.match(ruleBody(css, 'html:has(.stage[data-fs=pseudo]) :is(.ghost, .seal-ghost)'), /visibility:\s*hidden/);
});

test('file de la surcouche lisible sur tablette et téléphone couché ; artiste et demandeur lisibles sur téléphone', () => {
  const css = noComments(read(THEATER_CSS));
  // 34vw ne laissait au titre que quelques pixels à côté de la pochette, de la durée et des deux actions (768 px : 5 px)
  const w = ruleBody(css, '.th-queue').match(/width:\s*clamp\((\d+)px,\s*34vw,\s*380px\)/);
  assert.ok(w && Number(w[1]) >= 320, 'largeur plancher de la plaque');
  assert.match(css, /@media \(max-width: 1023px\) \{ \.th-dur \{ display: none; \} \}/, 'plaque étroite : la durée part');
  // téléphone couché : entre les deux bandeaux, la file ne montrait qu'une ligne et demie ; elle monte à côté du titre
  assert.match(css, /@media \(max-height: 520px\) and \(min-width: 701px\) \{\s*\.theater \{ grid-template-areas: "top queue" "\. queue" "bottom bottom"; \}/);
  // une colonne au seuil de FS_NARROW (file masquée d'emblée, Theater.tsx)
  const at = css.indexOf(`@media ${F.FS_NARROW} {`);
  assert.ok(at > 0, 'même seuil que FS_NARROW');
  const phone = css.slice(at, css.indexOf('\n}', at));
  assert.match(phone, /\.th-meta-line \{[^}]*flex-wrap:\s*wrap/, 'l’artiste et le demandeur sur deux lignes');
  assert.match(phone, /\.th-meta-line > \.dot-sep \{ display: none; \}/);
  assert.match(phone, /\.th-artist \{ flex-basis: 100%; \}/);
  assert.match(phone, /\.th-by \{ flex: 0 1 auto; \}/);
  assert.match(ruleBody(css, '.th-by'), /min-width:\s*0/);
  assert.match(ruleBody(css, '.th-by > span'), /text-overflow:\s*ellipsis/, 'le demandeur s’abrège seul');
  assert.match(code('src/components/Stage/Theater.tsx'), /<span>\{t\(keys\.plain, vars\)\}<\/span>/);
});

test('portal.css : un seul bloc de mouvement réduit (choreo-stage lit le dernier), le bouton d’entrée y est', () => {
  const css = noComments(read('src/components/Stage/portal.css'));
  assert.equal(css.match(/@media \(prefers-reduced-motion: reduce\)/g)?.length, 1);
  assert.match(css, /\.sync-btn, \.fs-btn\s*\{[^}]*height:\s*30px/, 'même bouton que « Synchro vidéo »');
  assert.match(css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)')), /\.fs-btn\s*\{\s*transition:\s*none/);
});

test('Portal : `.video` passe en plein écran, l’iframe ne bouge pas, la surcouche est son dernier enfant', () => {
  const portal = code('src/components/Stage/Portal.tsx');
  assert.match(portal, /<div className="video" ref=\{videoElRef\} data-fs=\{fullscreen\.mode \?\? undefined\} onDoubleClick=\{onDoubleClick\}>/);
  assert.match(portal, /<div className="yt" ref=\{wrapRef\} aria-hidden="true"\/>/, 'l’enveloppe du lecteur, inchangée');
  assert.match(portal, /return \(\s*<div className="portal">\s*<div className="video"/, 'ni enveloppe autour du portail ni de la vidéo');
  const video = portal.slice(portal.indexOf('<div className="video"'));
  const theater = video.indexOf('{fullscreen.mode && <Theater exit={fullscreen.exit}/>}');
  assert.ok(theater > video.indexOf('video-note'), 'après la note');
  assert.match(video.slice(theater), /^\{fullscreen\.mode && <Theater exit=\{fullscreen\.exit\}\/>\}\s*<\/div>\s*<\/div>/, 'dernier enfant de .video');
  assert.match(portal, /\(e\.target as Element\)\.closest\(FS_NO_DBLCLICK\)/, 'pas de double-clic sur une commande');
  // Suivant à la souris dans la surcouche : le Couronnement peut voler depuis la file, cachée sous la vidéo ; son fantôme
  // (dans <body>) y est invisible, sous la couche du dessus (API) ou caché par theater.css (repli) : en plein écran, quel
  // qu'il soit, le nouveau poster ne reste pas retenu (noir) pendant le vol
  assert.match(portal, /const ghostSeen = !fullscreen\.mode;/);
  assert.match(portal, /const flying = ghostSeen && crown\?\.mode === 'flight' && !crown\.landed;/);
  assert.match(portal, /cut=\{ghostSeen && p\.mode === 'flight'\}/);
});

test('Stage : un seul crochet, le bouton à côté de « Synchro vidéo », sortie sans titre, Portal jamais remonté', () => {
  const stage = code('src/components/Stage/Stage.tsx');
  assert.match(stage, /useFullscreen\(videoElRef, \(\) => \(fsBtnRef\.current\s*\?\? stageRef\.current\?\.querySelector<HTMLElement>\('\.night button, \.night a\[href\]'\)\)\?\.focus\(/,
    'focus rendu au bouton d’entrée ; parti avec le titre (fin de lecture), à l’appel de la nuit, jamais à <body>');
  assert.match(stage, /data-fs=\{fsMode \?\? undefined\}/);
  assert.match(stage, /fsExitDelay\(!!fsMode, day\)/);
  const foot = stage.slice(stage.indexOf('className="below-foot"'));
  assert.ok(foot.indexOf('<SyncOffset') >= 0 && foot.indexOf('<SyncOffset') < foot.indexOf('className="fs-btn"'), 'après la synchro');
  assert.match(foot, /<button ref=\{fsBtnRef\} type="button" className="fs-btn"[^>]*onClick=\{\(\) => fs\.toggle\(\)\}>/);
  // Entrée maintenue sur « Quitter le plein écran » : le focus revient ici, la répétition n'y rentre pas aussitôt
  assert.match(foot, /className="fs-btn"[^>]*onKeyDown=\{onFsKey\}/);
  assert.match(stage, /const onFsKey = \(e: KeyboardEvent<HTMLButtonElement>\): void => \{ if \(fsHeldKey\(e\)\) e\.preventDefault\(\); \};/);
  assert.match(foot, /className="fs-btn" aria-label=\{tx\('fullscreen\.enter'\)\}/, 'nommé même en icône seule (colonne étroite)');
  assert.match(noComments(read('src/components/Stage/portal.css')), /@container stage-col \(max-width: 660px\) \{[^@]*\.fs-btn \.fs-lbl \{ display: none; \}/);
  assert.match(stage, /\n\s*<Portal videoId=/, 'Portal rendu sans condition');
  assert.doesNotMatch(stage, /<Portal[^>]*\bkey=/, 'Portal sans clé : jamais remonté (l’iframe serait recréée)');
});

test('crochet : requestFullscreen dans le geste, état suivi par fullscreenchange (préfixe webkit), Échap du repli', () => {
  const hook = code('src/hooks/useFullscreen.ts');
  assert.match(hook, /'fullscreenchange', 'webkitfullscreenchange'/);
  assert.match(hook, /'fullscreenerror', 'webkitfullscreenerror'/);
  const enter = hook.slice(hook.indexOf('const enter = useCallback('), hook.indexOf('const exit = useCallback('));
  assert.match(enter, /\n\s*requestFs\(el\)\.catch\(\(\) => settle\(true\)\);/, 'appel direct, au niveau du gestionnaire');
  assert.doesNotMatch(enter, /await|requestAnimationFrame|=> requestFs/, 'appel synchrone : l’activation de l’utilisateur vaut encore');
  assert.match(enter, /asking\.current = setTimeout\(\(\) => settle\(true\), FS_ASK_MS\);/, 'demande sans réponse : repli, le bouton ne reste pas muet');
  assert.match(hook, /if \(mode !== 'pseudo'\) return;[\s\S]*?e\.key !== 'Escape' \|\| e\.defaultPrevented/);
});

test('surcouche : focus pris, piégé, rendu ; libellés ; aucun id ni classe de la scène ou de la file réutilisés', () => {
  const src = read('src/components/Stage/Theater.tsx');
  const th = code('src/components/Stage/Theater.tsx');
  assert.match(th, /root\.focus\(\{ preventScroll: true \}\);/);
  assert.match(th, /document\.addEventListener\('focusin', onFocusIn\);/);
  assert.match(th, /trapIndex\(list\.length, list\.indexOf\(document\.activeElement as HTMLElement\), e\.shiftKey\)/);
  assert.match(th, /createIdle\(FS_IDLE_MS, setIdle, hold,/);
  assert.match(th, /saveFsQueue\(\(\) => localStorage, next\)/);
  assert.match(th, /aria-expanded=\{queueOn\}/);
  // chaque bouton : type="button" et un nom (aria-label)
  const buttons = th.match(/<button [^>]*>/g) ?? [];
  assert.ok(buttons.length >= 4);
  for (const b of buttons) { assert.match(b, /type="button"/, b); assert.match(b, /aria-label=/, b); }
  // un seul data-clock="aria" (le cadran) ; ni l'id du titre de la scène, ni ceux du panneau, ni les classes de la file
  assert.match(th, /data-clock="cur"/);
  assert.match(th, /data-clock="tot"/);
  for (const bad of ['data-clock="aria"', 'NOW_TITLE_ID', "'now-title'", 'pane-queue', 'tab-queue', 'className="qlist"', 'className="row', 'className="act']) {
    assert.ok(!th.includes(bad), bad);
  }
  // le cœur du titre en cours (chansonnier du Roi), avant le bouton de la file
  assert.match(src, /<LikeButton track=\{current\} className="th-icon th-like"\/>\s*<button[^>]*fullscreen\.queueToggle/, 'cœur du titre en cours dans la surcouche');
  for (const [, key] of src.matchAll(/tx\('(fullscreen\.[\w.]+)'/g)) assert.notEqual(tx(key, { n: 2 }), key, key);
});

test('surcouche : le Héraut monté à côté est dans le piège du focus ; le reste de la page est inerte', () => {
  const th = code('src/components/Stage/Theater.tsx');
  // page.tsx monte le Héraut dans l'élément en plein écran (.video), frère de la surcouche, pas dedans
  assert.match(read('src/app/page.tsx'), /createPortal\(<Herald dock="center"\/>, fsHost\)/);
  assert.match(read('src/components/Herald/Herald.tsx'), /<section className="toasts"/);
  assert.match(th, /root\.parentElement\?\.querySelector<HTMLElement>\(':scope > \.toasts'\)/);
  // un focus posé sur « Annuler » (Tab, lecteur d'écran) y reste ; ailleurs, il revient à la surcouche
  assert.match(th, /return root\.contains\(n\) \|\| !!heraldOf\(root\)\?\.contains\(n\);/);
  assert.match(th, /if \(e\.target instanceof Node && !inside\(root, e\.target\)\) root\.focus\(\{ preventScroll: true \}\);/);
  // Tab : la surcouche puis le Héraut, plaques repliées ou sur le départ écartées ; d'où que parte la touche
  assert.match(th, /\[root, heraldOf\(root\)\]\.flatMap\(/);
  assert.match(th, /const OUT = '\[inert\], \.toast\[data-hidden\], \.toast\[data-leaving\]';/);
  assert.match(th, /document\.addEventListener\('keydown', onKeyDown\);/);
  assert.match(th, /document\.removeEventListener\('keydown', onKeyDown\);/);
  // « Annuler » joué : le Héraut rendrait le focus à la file, inerte ici ; tombé sur <body>, il revient à la surcouche
  assert.match(th, /document\.addEventListener\('focusout', onFocusOut\);/);
  assert.match(th, /if \(root\.isConnected && \(!at \|\| at === document\.body\)\) root\.focus\(\{ preventScroll: true \}\);/);
  // lecteurs d'écran : le reste de la page (hors de l'écran) est inerte le temps du plein écran
  assert.match(th, /const host = rootRef\.current\?\.parentElement;\s*return host \? inertOthers\(host, document\.body\) : undefined;/);
});

test('repos : une commande au focus du clavier retient les commandes ; au doigt, l’appui qui réveille n’actionne rien', () => {
  const th = code('src/components/Stage/Theater.tsx');
  const hold = th.slice(th.indexOf('const hold = '), th.indexOf('const rest = '));
  assert.match(hold, /keyed\(\)/, 'focus du clavier sur une commande : son anneau ne s’efface pas (WCAG 2.4.7)');
  assert.match(th, /root\.contains\(el\) && !!el\.closest\('\.th-ui'\) && keyboardFocus\(el\)/, ':focus-visible seulement, pas un clic');
  // l'appui à part : le repos est lu avant le réveil, le clic qui suit est avalé en capture (avant React et la commande)
  assert.doesNotMatch(th.match(/const WAKE = \[[^\]]*\]/)?.[0] ?? 'pointerdown', /pointerdown/);
  assert.match(th, /const down = \(e: PointerEvent\): void => \{ tap\.down\(e\.pointerType, rest\.idle\); rest\.wake\(\); \};/);
  assert.match(th, /root\.addEventListener\('pointerdown', down, \{ passive: true \}\);/);
  assert.match(th, /root\.addEventListener\('pointercancel', cancel\);/);
  assert.match(th, /root\.addEventListener\('click', eat, true\);/);
  assert.match(th, /if \(!tap\.eats\(e\.detail\)\) return;\s*e\.preventDefault\(\);\s*e\.stopPropagation\(\);/);
  assert.match(th, /root\.removeEventListener\('click', eat, true\);/);
});

test('file de la surcouche masquée d’emblée sur un téléphone debout, sauf choix du Roi', () => {
  const th = code('src/components/Stage/Theater.tsx');
  assert.match(th, /useState\(\(\) => loadFsQueue\(\(\) => localStorage,\s*typeof matchMedia === 'function' && matchMedia\(FS_NARROW\)\.matches\)\)/);
});

test('file de la surcouche : une action ne retombe pas sur la voisine (double-clic, Entrée maintenue)', () => {
  const th = code('src/components/Stage/Theater.tsx');
  // la ligne partie, la suivante glisse sous le pointeur : le second clic d'un double-clic attend l'accalmie (QueuePanel)
  assert.match(th, /const \[settle\] = useState\(createSettle\);/);
  const at = th.indexOf('const onListClick'), click = th.slice(at, th.indexOf('\n  };', at));
  const guard = click.indexOf('if (e.detail > 0 && settle.active(now)) return;');
  assert.ok(guard > 0, 'clic de pointeur pendant l’accalmie : ignoré (au clavier, detail 0, le focus a suivi exprès)');
  assert.ok(guard < click.indexOf('settle.start(now);') && click.indexOf('settle.start(now);') < click.indexOf('playerActions.'), 'accalmie posée avant l’action');
  assert.match(th, /onPointerMove=\{\(e\) => \{ settle\.move\(e\.clientX, e\.clientY, performance\.now\(\)\); \}\}/, 'le pointeur qui bouge la lève');
  // le focus suit la voisine (même bouton) : Entrée maintenue la retirerait ou la jouerait à son tour, toute la file y passerait
  assert.match(th, /if \(e\.repeat && e\.key === 'Enter' && \(e\.target as Element\)\.closest\('\[data-act\]'\)\) e\.preventDefault\(\);/);
  assert.match(th, /<ol className="th-list" ref=\{listRef\} onClick=\{onListClick\} onKeyDown=\{onListKeyDown\}/);
});

test('surcouche tout juste parue : le second clic d’un double-clic sur « Plein écran » n’atteint rien', () => {
  const th = code('src/components/Stage/Theater.tsx');
  assert.match(th, /const \[shownAt\] = useState\(\(\) => performance\.now\(\)\);/);
  assert.match(th, /if \(!fsSwallowClick\(e\.detail, performance\.now\(\) - shownAt\)\) return;\s*e\.preventDefault\(\);\s*e\.stopPropagation\(\);/);
  // en capture, sur la surcouche : ni la commande dessous (lecture, pause), ni le double-clic de .video (sortie aussitôt)
  assert.match(th, /onClickCapture=\{swallow\} onDoubleClickCapture=\{swallow\}/);
});

test('textes : section « fullscreen » complète, hors du deck', () => {
  for (const k of ['enter', 'enterTip', 'exit', 'exitTip', 'region', 'queue', 'queueToggle', 'queueShow', 'queueHide', 'current']) {
    assert.equal(typeof EXTRA.fullscreen[k], 'string', k);
  }
  assert.equal(tx('fullscreen.more', { n: 1 }), '…et 1 autre titre');
  assert.equal(tx('fullscreen.more', { n: 4 }), '…et 4 autres titres');
  assert.equal(tx('fullscreen.exit'), 'Quitter le plein écran');
});

test('page : en plein écran, saisie, « / » et « ? » ignorés avant tout effet ; Espace et Maj+→/← passent', () => {
  const page = read('src/app/page.tsx');
  assert.match(page, /import \{ FS_ACTIVE, fsSkips \} from '@\/lib\/stage\/fullscreen';/);
  const gate = page.indexOf('if (fsSkips(act) && document.querySelector(FS_ACTIVE)) return;');
  assert.ok(gate > 0, 'garde du plein écran');
  assert.ok(gate > page.indexOf('if (!s.guildId && PLAYS.includes(act)) return;'));
  assert.ok(gate < page.indexOf("if (act === 'type')"), 'avant la saisie directe (qui focaliserait la recherche cachée)');
  assert.ok(gate < page.indexOf('ev.preventDefault();'), 'la touche reste au navigateur');
  assert.equal(F.FS_ACTIVE, '.video[data-fs]');
  assert.deepEqual([...F.FS_SKIPPED].sort(), ['help', 'search', 'type']);
});
