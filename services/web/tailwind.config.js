/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        greg: {
          bg: '#0b1020',
          card: 'rgba(18, 25, 44, 0.82)',
          card2: 'rgba(18, 25, 44, 0.62)',
          dark: 'rgba(2, 6, 23, 0.25)',
          darker: 'rgba(2, 6, 23, 0.40)',
        },
        stroke: {
          DEFAULT: 'rgba(148, 163, 184, 0.18)',
          hover: 'rgba(148, 163, 184, 0.28)',
        },
        primary: {
          DEFAULT: '#6366f1',
          dark: '#4f46e5',
          light: '#818cf8',
        },
        ok: '#10b981',
        danger: '#ef4444',
        muted: '#94a3b8',
        txt: '#e5e7eb',
      },
      borderRadius: {
        greg: '16px',
      },
      boxShadow: {
        greg: '0 12px 40px rgba(0, 0, 0, 0.35)',
      },
    },
  },
  plugins: [],
};
