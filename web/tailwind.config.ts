import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        urgent: "#dc2626",
        high: "#ea580c",
        normal: "#0284c7",
        low: "#65748b",
        spam: "#737373",
      },
    },
  },
  plugins: [],
};
export default config;
