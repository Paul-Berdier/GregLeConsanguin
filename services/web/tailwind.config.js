/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          0: '#06080f',
          1: 'rgba(12, 16, 28, 0.85)',
          2: 'rgba(18, 24, 42, 0.72)',
          3: 'rgba(26, 32, 54, 0.60)',
        },
        accent: { DEFAULT: '#7c5cfc', light: '#a78bfa', dim: 'rgba(124, 92, 252, 0.15)' },
        teal:   { DEFAULT: '#2dd4bf', dim: 'rgba(45, 212, 191, 0.12)' },
        rose:   { DEFAULT: '#fb7185', dim: 'rgba(251, 113, 133, 0.12)' },
        txt:    { DEFAULT: '#e2e8f0', muted: '#64748b', dim: '#334155' },
        border: { DEFAULT: 'rgba(148, 163, 184, 0.10)', hover: 'rgba(148, 163, 184, 0.20)' },
      },
      fontFamily: {
        display: ['"Sora"', 'system-ui', 'sans-serif'],
        body:    ['"DM Sans"', 'system-ui', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'monospace'],
      },
      borderRadius: { xl2: '20px', xl3: '24px' },
      boxShadow: {
        glow: '0 0 40px rgba(124, 92, 252, 0.15)',
        deep: '0 20px 60px rgba(0, 0, 0, 0.5)',
        card: '0 8px 32px rgba(0, 0, 0, 0.3)',
      },
      keyframes: {
        'fade-up': { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        'pulse-ring': { '0%,100%': { boxShadow: '0 0 0 0 rgba(124,92,252,0)' }, '50%': { boxShadow: '0 0 0 8px rgba(124,92,252,0.15)' } },
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
