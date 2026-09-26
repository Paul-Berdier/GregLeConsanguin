/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        // Nuit gothique : tokens de src/theme/tokens.css
        nuit:    'var(--nuit)',
        nef:     'var(--nef)',
        voute:   'var(--voute)',
        os:      'var(--os)',
        cendre:  'var(--cendre)',
        or:      'var(--or)',
        gueules: 'var(--gueules)',

        // legacy: supprimé à l'étape 3
        surface: {
          0: 'var(--nuit)',
          1: 'var(--nef)',
          2: 'var(--voute)',
          3: 'var(--voute-2)',
        },
        // legacy: supprimé à l'étape 3
        accent: { DEFAULT: 'rgb(var(--lumiere-rgb))', light: 'var(--or)', dim: 'rgb(var(--lumiere-rgb) / .15)' },
        // legacy: supprimé à l'étape 3. DEFAULT en color-mix + <alpha-value> : un `var(--x)` nu
        // ferait disparaître les variantes à opacité (`bg-rose/20` n'est pas généré par Tailwind 3).
        teal:   { DEFAULT: 'color-mix(in srgb, var(--or) calc(<alpha-value> * 100%), transparent)', dim: 'color-mix(in srgb, var(--or) 12%, transparent)' },
        // legacy: supprimé à l'étape 3
        rose:   { DEFAULT: 'color-mix(in srgb, var(--gueules) calc(<alpha-value> * 100%), transparent)', dim: 'color-mix(in srgb, var(--gueules) 12%, transparent)' },
        // legacy: supprimé à l'étape 3
        txt:    { DEFAULT: 'var(--os)', muted: 'var(--cendre)', dim: 'var(--cendre-2)' },
        // legacy: supprimé à l'étape 3
        border: { DEFAULT: 'var(--hair)', hover: 'var(--hair-2)' },
      },
      fontFamily: {
        display: ['var(--f-display)'],
        body:    ['var(--f-ui)'],
        mono:    ['var(--f-ui)'],
      },
      borderRadius: { xl2: '20px', xl3: '24px' },
      boxShadow: {
        glow: '0 0 40px rgb(var(--lumiere-rgb) / .15)',
        deep: '0 20px 60px rgba(0, 0, 0, 0.5)',
        card: '0 8px 32px rgba(0, 0, 0, 0.3)',
      },
      keyframes: {
        'fade-up': { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        'pulse-ring': { '0%,100%': { boxShadow: '0 0 0 0 rgb(207 167 90 / 0)' }, '50%': { boxShadow: '0 0 0 8px rgb(207 167 90 / .15)' } },
        'gradient-shift': { '0%,100%': { backgroundPosition: '0% 50%' }, '50%': { backgroundPosition: '100% 50%' } },
        shimmer: { from: { backgroundPosition: '-200% 0' }, to: { backgroundPosition: '200% 0' } },
      },
      animation: {
        'fade-up': 'fade-up 0.4s ease-out',
        'pulse-ring': 'pulse-ring 2.5s ease-in-out infinite',
        'gradient-shift': 'gradient-shift 6s ease infinite',
        shimmer: 'shimmer 2s linear infinite',
      },
    },
  },
  plugins: [],
};
