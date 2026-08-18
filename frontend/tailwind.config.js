/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#f7f7f5',
        panel: '#ffffff',
        chrome: '#efeeea',
        thead: '#faf9f7',
        line: '#e2e1dd',
        'line-soft': '#f0efec',
        'line-mid': '#e7e6e1',
        'line-input': '#dedcd7',
        ink: '#1c1b19',
        'ink-2': '#2c2b28',
        'ink-3': '#4a4945',
        muted: '#6b6a65',
        dim: '#8b8a82',
        dimmer: '#9a998f',
        faint: '#a3a29a',
        accent: 'oklch(0.52 0.14 255)',
        'accent-dark': 'oklch(0.47 0.14 255)',
        ok: 'oklch(0.55 0.11 150)',
        amber: 'oklch(0.62 0.13 75)',
        orange: 'oklch(0.62 0.15 55)',
        danger: 'oklch(0.55 0.16 25)',
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", 'system-ui', 'sans-serif'],
        mono: ["'IBM Plex Mono'", 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
