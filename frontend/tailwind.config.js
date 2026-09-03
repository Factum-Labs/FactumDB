/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Light theme, cool neutrals + teal accent.
        // Anchors: #EEF2F0 ground, #858585 dim text, #63BDB5 / #15696F teal, #282828 ink.
        page: '#eef2f0',
        panel: '#ffffff',
        chrome: '#e4ebe9',
        thead: '#f4f7f6',
        line: '#d5dedb',
        'line-soft': '#e8eeec',
        'line-mid': '#dde5e3',
        'line-input': '#cbd6d3',
        ink: '#282828',
        'ink-2': '#333333',
        'ink-3': '#4e4e4e',
        muted: '#6e6e6e',
        dim: '#858585',
        dimmer: '#9a9a9a',
        faint: '#a8a8a8',
        accent: '#15696f',
        'accent-dark': '#0f4f54',
        'accent-light': '#63bdb5',
        'accent-soft': '#e2efee',
        ok: '#2f8a72',
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
