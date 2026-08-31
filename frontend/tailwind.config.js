/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Confidence colours — used throughout the interface.
        "conf-high": "#15803d", // green-700
        "conf-medium": "#b45309", // amber-700
        "conf-low": "#dc2626", // red-600
        // Band colours.
        "band-strong": "#15803d",
        "band-moderate": "#b45309",
        "band-low": "#dc2626",
      },
    },
  },
  plugins: [],
};
