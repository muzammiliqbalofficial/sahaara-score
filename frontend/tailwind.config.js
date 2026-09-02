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
        // Anomaly risk level colours.
        "risk-clean": "#16a34a",
        "risk-low": "#65a30d",
        "risk-moderate": "#d97706",
        "risk-high": "#ea580c",
        "risk-critical": "#dc2626",
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "pulse-glow": "pulseGlow 2s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(59,130,246,0.4)" },
          "50%": { boxShadow: "0 0 20px 4px rgba(59,130,246,0.2)" },
        },
      },
    },
  },
  plugins: [],
};
