import type { ThemeMode } from "../types";

export type ThemeVars = Record<string, string>;

// Moss-green / Willow-green / Pale-amber / Prussian-blue / Space-indigo palette
export const THEMES: Record<ThemeMode, ThemeVars> = {
    light: {
        // Backgrounds — warm parchment tones
        "--bg":       "#f3f9ec",   // willow-green-50
        "--bg2":      "#ffffff",
        "--bg3":      "#e6f3d8",   // willow-green-100
        "--bg4":      "#cee6b2",   // willow-green-200

        // Borders
        "--border":   "#b5da8b",   // willow-green-300
        "--border2":  "#9ccd65",   // willow-green-400

        // Primary accent — moss-green
        "--gold":     "#589b31",   // moss-green-600
        "--gold2":    "#427425",   // moss-green-700
        "--gold-dim": "rgba(88,155,49,0.10)",
        "--gold-glow":"rgba(88,155,49,0.07)",

        // Text
        "--text":     "#16270c",   // moss-green-900
        "--text-dim": "#699a32",   // willow-green-600
        "--text-mid": "#4f7425",   // willow-green-700

        // Semantic colours
        "--green":    "#589b31",   // moss-green-600
        "--green-dim":"rgba(88,155,49,0.10)",

        "--red":      "#c0392b",
        "--red-dim":  "rgba(192,57,43,0.10)",

        "--blue":     "#2a48a2",   // prussian-blue-600
        "--blue-dim": "rgba(42,72,162,0.10)",

        "--amber":    "#bcc13e",   // pale-amber-500
        "--amber-dim":"rgba(188,193,62,0.12)",

        "--indigo":   "#3d528f",   // space-indigo-600
        "--indigo-dim":"rgba(61,82,143,0.10)",

        "--shadow":   "0 1px 4px rgba(22,39,12,0.07), 0 4px 20px rgba(22,39,12,0.04)",
        "--shadow-md":"0 4px 16px rgba(22,39,12,0.10)",
    },
    dark: {
        "--bg":       "#0f1b09",   // moss-green-950
        "--bg2":      "#16270c",   // moss-green-900
        "--bg3":      "#121b09",   // willow-green-950
        "--bg4":      "#1a270c",   // willow-green-900

        "--border":   "#2c4e18",   // moss-green-800
        "--border2":  "#427425",   // moss-green-700

        "--gold":     "#84c13e",   // willow-green-500
        "--gold2":    "#9ccd65",   // willow-green-400
        "--gold-dim": "rgba(132,193,62,0.12)",
        "--gold-glow":"rgba(132,193,62,0.06)",

        "--text":     "#f3f9ec",   // willow-green-50
        "--text-dim": "#699a32",   // willow-green-600
        "--text-mid": "#b5da8b",   // willow-green-300

        "--green":    "#84c13e",
        "--green-dim":"rgba(132,193,62,0.12)",

        "--red":      "#e05555",
        "--red-dim":  "rgba(224,85,85,0.12)",

        "--blue":     "#5d7bd5",   // prussian-blue-400
        "--blue-dim": "rgba(93,123,213,0.12)",

        "--amber":    "#d7da8b",   // pale-amber-300
        "--amber-dim":"rgba(215,218,139,0.12)",

        "--indigo":   "#7085c2",   // space-indigo-400
        "--indigo-dim":"rgba(112,133,194,0.10)",

        "--shadow":   "0 1px 4px rgba(0,0,0,0.3), 0 4px 20px rgba(0,0,0,0.2)",
        "--shadow-md":"0 4px 16px rgba(0,0,0,0.35)",
    },
};