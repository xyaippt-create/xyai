/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Didot", "Bodoni 72", "Times New Roman", "serif"],
        sans: ["Inter", "Microsoft YaHei UI", "Microsoft YaHei", "sans-serif"],
        serif: ["Cormorant Garamond", "Times New Roman", "serif"]
      },
      colors: {
        polar: {
          950: "#031014",
          900: "#07191f",
          800: "#0b2730",
          300: "#9fd9df",
          100: "#e7fbff"
        },
        glacier: "#8ff4ff",
        aurora: "#b7ffd4",
        ember: "#f6d6a6"
      },
      boxShadow: {
        cinematic: "0 40px 140px rgba(19, 245, 255, 0.16)",
        insetGlow: "inset 0 0 80px rgba(143, 244, 255, 0.12)"
      }
    }
  },
  plugins: []
};
