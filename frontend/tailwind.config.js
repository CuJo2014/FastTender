/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Семантические цвета под confidence
        "conf-high": "#16a34a",   // зелёный — авто-подтверждение
        "conf-medium": "#f59e0b", // оранжевый — на проверку
        "conf-low": "#dc2626",    // красный — не найдено
      },
    },
  },
  plugins: [],
};
