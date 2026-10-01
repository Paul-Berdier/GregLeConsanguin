// ── SVG Icons ──
export const I = {
  play:   <path fill="currentColor" d="M8 5v14l11-7z"/>,
  pause:  <path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z"/>,
  skip:   <path fill="currentColor" d="M7 6v12l8.5-6zM17 6h2v12h-2z"/>,
  prev:   <path fill="currentColor" d="M7 6h2v12H7zm3 6l10 6V6z"/>,
  stop:   <path fill="currentColor" d="M6 6h12v12H6z"/>,
  repeat: <path fill="currentColor" d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z"/>,
  trash:  <path fill="currentColor" d="M9 3h6l1 2h5v2H3V5h5zm1 6h2v10h-2zm4 0h2v10h-2z"/>,
  search: <path fill="currentColor" d="M10 4a6 6 0 1 0 3.6 10.8l4.8 4.8 1.4-1.4-4.8-4.8A6 6 0 0 0 10 4zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"/>,
  music:  <path fill="currentColor" d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/>,
  video:  <path fill="currentColor" d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z"/>,
};
export function Ic({ icon, size = 20 }: { icon: keyof typeof I; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} className="flex-shrink-0">{I[icon]}</svg>;
}
