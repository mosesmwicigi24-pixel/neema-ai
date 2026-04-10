import React from "react";
import type { ThemeVars } from "../../lib/themes";

interface GlobalStylesProps {
    themeVars: ThemeVars;
}

export function GlobalStyles({ themeVars }: GlobalStylesProps): React.ReactElement {
    const cssVars = Object.entries(themeVars)
        .map(([k, v]) => `${k}: ${v}`)
        .join("; ");

    return (
        <>
            <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap');

        :root {
            ${cssVars};
            --font-body: 'Plus Jakarta Sans', system-ui, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: var(--font-body); }
        html, body { height: 100%; }
        body {
            background: var(--bg);
            -webkit-text-size-adjust: 100%;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #dde4d6; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #c5d0bc; }
        .scrollbar-none::-webkit-scrollbar { display: none; }
        .scrollbar-none { scrollbar-width: none; }

        /* Focus ring */
        input:focus, textarea:focus, select:focus {
            border-color: #589b31 !important;
            box-shadow: 0 0 0 3px rgba(88,155,49,0.12);
            outline: none;
        }
        *:focus-visible { outline: 2px solid #589b31; outline-offset: 2px; border-radius: 6px; }

        input, textarea, select {
            font-size: 13px;
            font-family: var(--font-body);
        }
        select {
            background: var(--bg3);
            border: 1px solid var(--border);
            border-radius: 7px;
            color: var(--text);
            padding: 7px 12px;
            outline: none;
            cursor: pointer;
        }

        /* Animations */
        @keyframes fadeSlide { from { opacity:0; transform:translateX(8px); } to { opacity:1; transform:translateX(0); } }
        @keyframes fadeUp    { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
        @keyframes toastIn   { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeIn    { from { opacity:0; } to { opacity:1; } }
        @keyframes pulse     { 0%,100%{opacity:1} 50%{opacity:.5} }

        .neema-modal { animation: fadeUp 0.2s ease; }
        @media (min-width: 768px) {
            .neema-modal { border-radius: 12px !important; max-width: 520px !important; width: 100% !important; position: relative; }
        }
        .animate-in    { animation: fadeIn 0.18s ease; }
        .action-strip  { scrollbar-width: none; -ms-overflow-style: none; }
        .action-strip::-webkit-scrollbar { display: none; }
        .bottom-nav    { padding-bottom: env(safe-area-inset-bottom, 0px); }
        .pb-safe       { padding-bottom: env(safe-area-inset-bottom, 0px); }
        .h-dvh         { height: 100dvh; }

        /* ── Tailwind green → moss-green overrides ───────────────────────────── */
        .bg-green-700  { background-color: #427425 !important; }
        .bg-green-600  { background-color: #589b31 !important; }
        .bg-green-500  { background-color: #6ec23d !important; }
        .bg-green-50   { background-color: #f0f9ec !important; }
        .bg-green-100  { background-color: #e2f3d8 !important; }
        .text-green-700{ color: #427425 !important; }
        .text-green-800{ color: #2c4e18 !important; }
        .text-green-600{ color: #559b31 !important; }
        .border-green-700 { border-color: #427425 !important; }
        .border-green-600 { border-color: #589b31 !important; }
        .hover\\:bg-green-600:hover { background-color: #589b31 !important; }
        .focus\\:ring-green-600:focus { --tw-ring-color: #589b31 !important; }
        .ring-green-600 { --tw-ring-color: #589b31; }

        /* ── Sidebar: light icon-rail (overrides dark gray Tailwind classes) ── */
        .bg-gray-950 { background-color: #ffffff !important; }
        .bg-gray-900 { background-color: #f7f8f5 !important; }
        .bg-gray-800 { background-color: #eef1ea !important; }
        .bg-gray-800\\/60 { background-color: rgba(238,241,234,0.6) !important; }
        .bg-gray-700\\/60 { background-color: rgba(228,233,222,0.6) !important; }
        .border-gray-800 { border-color: #e8ebe3 !important; }
        .border-gray-800\\/60 { border-color: rgba(232,235,227,0.6) !important; }
        .border-gray-700 { border-color: #dde4d6 !important; }
        .text-gray-600  { color: #7a8c70 !important; }
        .text-gray-500  { color: #8a9e80 !important; }
        .text-gray-400  { color: #699a32 !important; }
        .text-gray-300  { color: #3d5a30 !important; }
        .text-gray-200  { color: #2c4e18 !important; }
        .hover\\:bg-gray-800\\/70:hover { background-color: rgba(238,241,234,0.7) !important; }
        .hover\\:bg-gray-800:hover { background-color: #eef1ea !important; }

        button { transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease; }
      `}</style>
        </>
    );
}