"use client";

// Emoji picker for the reply composer (owner, 2026-11-09). No dependency:
// a curated set an agent actually uses with customers, each with search
// words, in WhatsApp's category order, plus the agent's recent picks
// (this browser only). Emojis are plain Unicode text — they are stored,
// rendered and sent exactly like any other character of the reply.

import { useEffect, useMemo, useRef, useState } from "react";

type E = [emoji: string, words: string];

const CATEGORIES: { id: string; label: string; icon: string; items: E[] }[] = [
    { id: "smileys", label: "Smileys", icon: "😊", items: [
        ["😀", "grin smile happy"], ["😃", "smile happy joy"], ["😄", "smile laugh happy"], ["😁", "grin beam"],
        ["😆", "laugh lol"], ["😅", "sweat relief laugh"], ["😂", "joy tears laugh lol"], ["🤣", "rofl laugh"],
        ["🙂", "slight smile ok"], ["🙃", "upside down"], ["😉", "wink"], ["😊", "blush smile thanks"],
        ["😇", "angel innocent blessed"], ["🥰", "love hearts"], ["😍", "heart eyes love"], ["🤩", "star struck wow"],
        ["😘", "kiss"], ["😋", "yum tasty"], ["😜", "wink tongue"], ["🤗", "hug welcome"],
        ["🤭", "oops giggle"], ["🤔", "think hmm"], ["🤐", "zip quiet"], ["😐", "neutral"],
        ["😏", "smirk"], ["😌", "relieved calm"], ["😴", "sleep"], ["😷", "mask sick"],
        ["🥳", "party celebrate"], ["😎", "cool sunglasses"], ["🤓", "nerd"], ["😕", "confused"],
        ["😟", "worried"], ["😮", "wow surprised"], ["😲", "astonished shock"], ["🥺", "pleading please"],
        ["😢", "cry sad"], ["😭", "sob cry"], ["😤", "huff"], ["😡", "angry"],
        ["🤯", "mind blown"], ["😳", "flushed embarrassed"], ["🙄", "eye roll"], ["😬", "grimace awkward"],
    ] },
    { id: "gestures", label: "People", icon: "👍", items: [
        ["👍", "thumbs up yes ok good like"], ["👎", "thumbs down no"], ["👌", "ok perfect"], ["✌️", "peace victory"],
        ["🤞", "fingers crossed luck"], ["🤝", "handshake deal agree"], ["🙏", "pray please thanks amen bless"], ["👏", "clap congrats"],
        ["🙌", "raise hands praise hallelujah"], ["👋", "wave hello hi bye"], ["💪", "strong muscle"], ["✍️", "write sign"],
        ["👉", "point right"], ["👈", "point left"], ["👆", "point up"], ["👇", "point down"],
        ["🫶", "heart hands love"], ["🤲", "palms up prayer"], ["👀", "eyes look"], ["🧠", "brain"],
        ["👶", "baby"], ["👦", "boy"], ["👧", "girl"], ["👨", "man"], ["👩", "woman"],
        ["🧑‍💼", "office worker"], ["👰", "bride wedding"], ["🤵", "groom wedding"], ["👪", "family"],
        ["⛪", "church"], ["🧕", "headscarf"], ["🙋", "raise hand question"], ["🤷", "shrug"],
    ] },
    { id: "hearts", label: "Symbols", icon: "❤️", items: [
        ["❤️", "heart love red"], ["🧡", "orange heart"], ["💛", "yellow heart"], ["💚", "green heart"],
        ["💙", "blue heart"], ["💜", "purple heart"], ["🤍", "white heart"], ["🖤", "black heart"],
        ["💖", "sparkle heart"], ["💕", "two hearts"], ["💯", "hundred perfect"], ["✅", "check done yes tick"],
        ["☑️", "check box"], ["✔️", "check mark"], ["❌", "cross no wrong"], ["⚠️", "warning"],
        ["❗", "exclamation important"], ["❓", "question"], ["⭐", "star"], ["🌟", "glowing star"],
        ["✨", "sparkles new"], ["🔥", "fire hot"], ["💡", "idea bulb"], ["📌", "pin"],
        ["⏰", "alarm time"], ["⏳", "hourglass wait"], ["✝️", "cross christian"], ["🕊️", "dove peace"],
        ["➡️", "arrow right"], ["⬅️", "arrow left"], ["🔁", "repeat"], ["🆕", "new"],
    ] },
    { id: "business", label: "Business", icon: "📦", items: [
        ["📦", "package parcel delivery order"], ["🚚", "truck delivery shipping"], ["✈️", "plane flight shipping abroad"], ["🛍️", "shopping bags"],
        ["🛒", "cart shopping"], ["🏷️", "tag price label"], ["💰", "money bag"], ["💵", "dollar cash"],
        ["💳", "card payment"], ["🧾", "receipt invoice"], ["📱", "phone mobile mpesa"], ["📞", "call phone"],
        ["📧", "email"], ["📍", "location pin address"], ["🗺️", "map"], ["🏠", "home house"],
        ["🏪", "shop store"], ["📅", "calendar date"], ["🗓️", "schedule"], ["📝", "note memo"],
        ["📄", "document page"], ["📎", "attachment clip"], ["📷", "camera photo"], ["🎥", "video camera"],
        ["🎁", "gift present"], ["🎉", "party celebrate tada"], ["🎊", "confetti"], ["🏆", "trophy"],
        ["👗", "dress"], ["👔", "shirt tie"], ["🧵", "thread sewing tailor"], ["✂️", "scissors cut"],
        ["📏", "ruler measure size"], ["🧥", "coat robe"], ["👘", "robe kimono vestment"], ["🎓", "graduation"],
    ] },
    { id: "nature", label: "Nature", icon: "🌸", items: [
        ["🌸", "blossom flower"], ["🌹", "rose"], ["🌻", "sunflower"], ["🌿", "herb leaf"],
        ["🌍", "globe africa earth world"], ["☀️", "sun"], ["🌙", "moon night"], ["🌧️", "rain"],
        ["🌈", "rainbow"], ["⛅", "cloud sun"], ["❄️", "snow"], ["🍞", "bread"],
        ["🍷", "wine"], ["☕", "coffee tea"], ["🍰", "cake"], ["🎂", "birthday cake"],
    ] },
];

const RECENT_KEY = "neema.composer.recentEmoji";
const RECENT_MAX = 24;

function readRecent(): string[] {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").slice(0, RECENT_MAX); }
    catch { return []; }
}

export function rememberEmoji(e: string) {
    try {
        const next = [e, ...readRecent().filter((x) => x !== e)].slice(0, RECENT_MAX);
        localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    } catch { /* private window: no memory, still works */ }
}

export function EmojiPicker({ onPick, onClose }: { onPick: (emoji: string) => void; onClose: () => void }) {
    const [q, setQ] = useState("");
    const [recent] = useState<string[]>(readRecent);
    const [cat, setCat] = useState<string>(recent.length ? "recent" : CATEGORIES[0].id);
    const box = useRef<HTMLDivElement>(null);
    const search = useRef<HTMLInputElement>(null);

    // Close on outside click / Escape; focus the search like iMessage.
    useEffect(() => {
        search.current?.focus();
        const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) onClose(); };
        const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
        document.addEventListener("mousedown", down);
        document.addEventListener("keydown", key);
        return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
    }, [onClose]);

    const shown = useMemo<string[]>(() => {
        const term = q.trim().toLowerCase();
        if (term) {
            const all = CATEGORIES.flatMap((c) => c.items);
            return all.filter(([, w]) => w.includes(term)).map(([e]) => e);
        }
        if (cat === "recent") return recent;
        return (CATEGORIES.find((c) => c.id === cat)?.items ?? []).map(([e]) => e);
    }, [q, cat, recent]);

    const pick = (e: string) => { rememberEmoji(e); onPick(e); };

    return (
        <div ref={box} role="dialog" aria-label="Emoji"
             className="absolute bottom-full right-0 mb-2 z-30 w-[min(320px,100%)] rounded-2xl bg-white shadow-[0_8px_30px_rgba(28,41,23,0.12)] border border-[#e5e8e2] overflow-hidden animate-in fade-in slide-in-from-bottom-1 duration-150">
            <div className="p-2 border-b border-[#eef1ea]">
                <input ref={search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search emoji"
                       className="w-full h-8 px-3 text-[13px] rounded-lg bg-[#f6f7f5] border border-[#e5e8e2] focus:outline-none focus:ring-2 focus:ring-[#f59e0b]/50" />
            </div>
            {!q && (
                <div className="flex items-center gap-0.5 px-1.5 pt-1.5" role="tablist">
                    {recent.length > 0 && (
                        <CatTab active={cat === "recent"} onClick={() => setCat("recent")} label="Recent" icon="🕘" />
                    )}
                    {CATEGORIES.map((c) => (
                        <CatTab key={c.id} active={cat === c.id} onClick={() => setCat(c.id)} label={c.label} icon={c.icon} />
                    ))}
                </div>
            )}
            <div className="h-52 overflow-y-auto px-1.5 py-1.5 grid grid-cols-8 gap-0.5 content-start">
                {shown.map((e) => (
                    <button key={e} type="button" onClick={() => pick(e)} title={e}
                            className="h-9 w-full rounded-lg text-[22px] leading-none hover:bg-[#f3f5f0] active:scale-90 transition-transform">
                        {e}
                    </button>
                ))}
                {shown.length === 0 && (
                    <p className="col-span-8 text-center text-xs text-stone-400 py-8">No emoji matches “{q}”</p>
                )}
            </div>
        </div>
    );
}

function CatTab({ active, onClick, label, icon }: { active: boolean; onClick: () => void; label: string; icon: string }) {
    return (
        <button type="button" role="tab" aria-selected={active} title={label} onClick={onClick}
                className={`h-8 w-8 rounded-lg text-base flex items-center justify-center transition-colors ${active ? "bg-[#fef3c7]" : "hover:bg-[#f3f5f0]"}`}>
            {icon}
        </button>
    );
}
