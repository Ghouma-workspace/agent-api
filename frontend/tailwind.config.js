/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#0e0f11",
        panel: "#17181b",
        accent: "#6366f1",
      },
    },
  },
  plugins: [],
};
