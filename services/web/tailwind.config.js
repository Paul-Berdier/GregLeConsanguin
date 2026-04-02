/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        parchment: {
          50: '#f5f0e8',
          100: '#e8dcc8',
          200: '#d4c5a9',
          300: '#bda87d',
          400: '#a68e5a',
          500: '#8b7d6b',
          600: '#6b5e4a',
          700: '#4a3f30',
          800: '#2d2418',
          900: '#1a1410',
          950: '#0f0c08',
        },
        gold: {
          DEFAULT: '#c9a84c',
          light: '#e6c45c',
          dark: '#9a7d30',
          muted: 'rgba(201, 168, 76, 0.15)',
        },
        crimson: {
          DEFAULT: '#8b2e2e',
          light: '#a63d3d',
          dark: '#6b1f1f',
        },
        emerald: {
          DEFAULT: '#2e6b4f',
          light: '#3d7a5a',
        },
      },
      fontFamily: {
        medieval: ['MedievalSharp', 'Georgia', 'serif'],
        body: ['Crimson Text', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        medieval: '8px',
      },
      boxShadow: {
        medieval: '0 4px 20px rgba(0, 0, 0, 0.4), 0 0 40px rgba(201, 168, 76, 0.05)',
        'medieval-hover': '0 8px 30px rgba(0, 0, 0, 0.5), 0 0 60px rgba(201, 168, 76, 0.1)',
      },
    },
  },
  plugins: [],
};
