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
        @import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&display=swap');
        :root { ${cssVars}; --font-body: 'Geist', system-ui, sans-serif; --font-mono: 'JetBrains Mono', monospace; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: var(--font-body); }
        html, body { height: 100%; }
        body { background: var(--bg); -webkit-text-size-adjust: 100%; }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
        .scrollbar-none::-webkit-scrollbar { display: none; }
        .scrollbar-none { scrollbar-width: none; }

        /* Focus ring uses moss-green accent */
        input:focus, textarea:focus, select:focus {
            border-color: #589b31 !important;
            box-shadow: 0 0 0 3px rgba(88,155,49,0.15);
            outline: none;
        }
        *:focus-visible { outline: 2px solid #589b31; outline-offset: 2px; border-radius: 6px; }

        input, textarea, select { font-size: 13px; font-family: var(--font-body); }
        select { background: var(--bg3); border: 1px solid var(--border); border-radius: 7px; color: var(--text); padding: 7px 12px; outline: none; cursor: pointer; }

        /* Animations */
        @keyframes fadeSlide { from { opacity:0; transform:translateX(8px); } to { opacity:1; transform:translateX(0); } }
        @keyframes fadeUp    { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
        @keyframes toastIn   { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeIn    { from { opacity:0; } to { opacity:1; } }
        @keyframes pulse     { 0%,100%{opacity:1} 50%{opacity:.5} }

        .neema-modal { animation: fadeUp 0.22s ease; }
        @media (min-width: 768px) {
            .neema-modal { border-radius: 14px !important; max-width: 520px !important; width: 100% !important; position: relative; }
        }
        .animate-in    { animation: fadeIn 0.18s ease; }
        .action-strip  { scrollbar-width: none; -ms-overflow-style: none; }
        .action-strip::-webkit-scrollbar { display: none; }
        .bottom-nav    { padding-bottom: env(safe-area-inset-bottom, 0px); }
        .pb-safe       { padding-bottom: env(safe-area-inset-bottom, 0px); }
        .h-dvh         { height: 100dvh; }

        /* Tailwind green overrides → moss-green */
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

        /* Sidebar dark uses palette */
        .bg-gray-950 { background-color: #0f1b09 !important; }
        .bg-gray-900 { background-color: #16270c !important; }
        .bg-gray-800 { background-color: #2c4e18 !important; }
        .border-gray-800 { border-color: #2c4e18 !important; }
        .border-gray-700 { border-color: #427425 !important; }
        .text-gray-400 { color: #699a32 !important; }
        .text-gray-300 { color: #9ccd65 !important; }
        .hover\\:bg-gray-800\\/70:hover { background-color: rgba(44,78,24,0.7) !important; }
      `}</style>
        </>
    );
}