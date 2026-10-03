/** @type {import('tailwindcss').Config} */
const brandScale = (name) => {
  const v = (step) => `rgb(var(--c-${name}${step ? "-" + step : ""}) / <alpha-value>)`;
  const scale = { DEFAULT: v("") };
  for (const step of [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]) scale[step] = v(step);
  return scale;
};

module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "turf-green": {
          50: "#f0f7f3",
          100: "#d9eee2",
          200: "#b3ddc5",
          300: "#7ec4a0",
          400: "#4da87a",
          500: "#3a855f",
          600: "#2F6E47",
          700: "#245737",
          800: "#1a3f28",
          900: "#112819",
        },
        "golden-bronze": {
          50: "#fdf8ed",
          100: "#faedcf",
          200: "#f4d99f",
          300: "#D8A843",
          400: "#c99030",
          500: "#b07a22",
          600: "#8e601a",
          700: "#6d4913",
          800: "#4d330d",
          900: "#2f1f08",
        },
        carbon: {
          50:  "#f5f4f2",
          100: "#e8e7e4",
          200: "#d2d0cc",
          300: "#b4b1ac",
          400: "#8f8c87",
          500: "#6b6865",
          600: "#545250",
          700: "#3b3a38",
          800: "#181716",
          900: "#09090b",
        },
        parchment: "#F6F4F0",
        "deep-space": {
          50:  "#eef2f8",
          100: "#d4dff0",
          200: "#aabfe0",
          300: "#7a9bcc",
          400: "#4e79b8",
          500: "#243C5A",
          600: "#1e3249",
          700: "#172638",
          800: "#101928",
          900: "#090f18",
        },
        "blue-bell": "#4A9EDD",
        bubblegum: "#E85D75",
        // Brand palette for the public booking site, portal and email. The
        // values are CSS variables, not hex: app/core/branding.py expands the
        // RMS_BRAND_COLOR_* settings into full scales at runtime, so re-branding
        // is configuration only. Defaults live in app/static/src/css/main.css.
        primary: brandScale("primary"),
        accent: brandScale("accent"),
        highlight: brandScale("highlight"),
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        footer: "rgb(var(--c-footer) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
        heading: ["var(--font-heading)"],
        body: ["var(--font-body)"],
      },
    },
  },
  plugins: [],
};
