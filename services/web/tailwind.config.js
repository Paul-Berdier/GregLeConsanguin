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
