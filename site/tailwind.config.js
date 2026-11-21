/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // One disciplined palette: obsidian, bone, zinc, and a single champagne accent.
      colors: {
        obsidian: '#09090B',
        surface: '#121215',
        bone: '#F4F4F5',
        mute: '#8E8E93',
        gold: { DEFAULT: '#D4AF7A', soft: '#E6CFA6', deep: '#A8865A' },
      },
      fontFamily: {
        sans: ['Heebo', 'Arial', 'sans-serif'],
        display: ['Rubik', 'Heebo', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
