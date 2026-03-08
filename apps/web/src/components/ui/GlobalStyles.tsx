import React from "react";
import type { ThemeVars } from "../../lib/themes";

interface GlobalStylesProps {
    themeVars: ThemeVars;
}

export function GlobalStyles({
    themeVars,
}: GlobalStylesProps): React.ReactElement {
    const cssVars = Object.entries(themeVars)
        .map(([k, v]) => `${k}: ${v}`)
        .join("; ");

    return (
        <>
            <style>{`
        :root { ${cssVars}; --font-body: 'Lato', sans-serif; --font-mono: 'JetBrains Mono', monospace; --font-serif: 'Playfair Display', serif; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; }
        body { background: var(--bg); -webkit-text-size-adjust: 100%; }

        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }

        input:focus, textarea:focus, select:focus { border-color: var(--gold) !important; box-shadow: 0 0 0 3px var(--gold-dim); }
        button:hover:not(:disabled) { opacity: 0.82; }
        input, textarea, select { font-size: 16px !important; }
        select { background: var(--bg3); border: 1px solid var(--border); border-radius: 7px; color: var(--text); padding: 9px 13px; font-family: var(--font-body); outline: none; cursor: pointer; }

        @keyframes fadeSlide { from { opacity:0; transform:translateX(8px); } to { opacity:1; transform:translateX(0); } }
        @keyframes fadeUp    { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
        @keyframes toastIn   { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }

        .neema-modal { animation: fadeUp 0.25s ease; }
        @media (min-width: 768px) {
          .neema-modal { border-radius: 14px !important; max-width: 520px !important; width: 100% !important; position: relative; }
        }
        .action-strip { scrollbar-width: none; -ms-overflow-style: none; }
        .action-strip::-webkit-scrollbar { display: none; }
        .bottom-nav { padding-bottom: env(safe-area-inset-bottom, 0px); }
      `}</style>
            <link
                href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=JetBrains+Mono:wght@300;400;500&family=Lato:wght@300;400;500;700&display=swap"
                rel="stylesheet"
            />
        </>
    );
}
