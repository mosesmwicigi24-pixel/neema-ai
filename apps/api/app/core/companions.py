"""THE COMPANION MAP, grounded in the hub (owner, 2026-09-26: "upselling
naturally… closing deals effectively").

The prompt tells Neema what a buyer of an item completes it with (a cassock
→ its stole, cincture, shirt and collar; a tray → cups, wafers and wine). A
suggestion is only worth making with a real row and a real price behind it,
so every search result carries:

  goes_with     — the humblest hub row of each companion kind (CHEAPEST
                  FIRST), name and price: the one suggestion is a fact.
  part_of_set   — for a piece the hub also sells inside a set ("Cassock"
                  inside "Cassock Set"): the set's name and price, so "the
                  cassock alone is $120; the complete set is $200" is grounded
                  both ways (A SET IS PRICED AS ITS TOTAL).
  pieces_priced — for a set row: each listed piece resolved to the hub row it
                  is sold as on its own, with that row's price.

Kinds come from post_catalog.product_kind (the head noun of the hub name,
plural stripped): "Silver Communion Cups" → cup, "CINCTURE BELT" → belt.
Best-effort everywhere: an empty answer never costs a reply."""
from __future__ import annotations

from app.services.post_catalog import (_kinds_of, _piece_kind, _name_tokens,
                                       is_set_row, product_kind, set_components)

# kind → the companions a buyer completes it with, in selling order. Each
# entry is (kind, preferred name word or None): a cassock's "belt" is the
# CINCTURE belt, never the usher belt the cheapest-first rule would pick.
COMPANIONS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "cassock": (("stole", None), ("belt", "cincture"), ("rope", "cincture"), ("shirt", None),
                ("collar", None)),
    "surplice": (("cassock", None), ("stole", None)),
    "shirt": (("collar", None),),
    "collar": (("shirt", None),),
    "chasuble": (("stole", None), ("alb", None)),
    "alb": (("rope", "cincture"), ("belt", "cincture"), ("stole", None)),
    "cope": (("stole", None), ("mitre", None)),
    "gown": (("stole", None), ("hood", None), ("cap", None)),
    "tray": (("cup", None), ("bread", None), ("wafer", None), ("host", None), ("wine", None)),
    "cup": (("tray", None), ("bread", None), ("wafer", None), ("wine", None)),
    "chalice": (("paten", None), ("wine", None), ("host", None), ("bread", None)),
    "paten": (("chalice", None),),
    "bread": (("wine", None), ("cup", None), ("tray", None)),
    "wafer": (("wine", None), ("cup", None), ("tray", None)),
    "host": (("wine", None), ("cup", None), ("tray", None)),
    "wine": (("bread", None), ("wafer", None), ("host", None), ("cup", None)),
    "thurible": (("incense", None), ("charcoal", None), ("boat", None)),
    "incense": (("thurible", None), ("charcoal", None)),
    "mitre": (("cross", "pectoral"), ("ring", None), ("crozier", None)),
    "ring": (("cross", "pectoral"), ("mitre", None)),
    "cross": (("ring", None), ("chain", None)),
    "tallit": (("cap", None),),
}


def _kes(row: dict) -> float:
    for k in ("price_kes", "price"):
        try:
            v = float(row.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return float("inf")


def _tokens(text: str) -> set[str]:
    return set(_name_tokens(text or ""))


def _pick(rows: list[dict], prefer: str | None, like: str = "") -> dict | None:
    """The row to name for a kind: one carrying the preferred word when any
    does, the most name-overlap with `like` when given, the cheapest among
    equals, the plainer name among price ties."""
    if not rows:
        return None
    pool = rows
    if prefer:
        pref = [r for r in rows if prefer in _tokens(r.get("name") or "")]
        pool = pref or rows
    like_t = _tokens(like)

    def _score(r: dict):
        nm = _tokens(r.get("name") or "")
        return (-len(nm & like_t) if like_t else 0, _kes(r), len(nm))
    return sorted(pool, key=_score)[0]


def goes_with(row: dict | None, catalog: list[dict] | None, limit: int = 3) -> list[dict]:
    """The companion rows of `row` — at most `limit`, one per companion kind,
    the humblest of each kind (the buyer climbs), never the row itself and
    never a set (a set is already complete)."""
    if not row or not catalog or is_set_row(row):
        return []
    kind = product_kind(row)
    plan = COMPANIONS.get(kind)
    if not plan:
        return []
    idx = _kinds_of(catalog)
    out: list[dict] = []
    seen: set[str] = set()
    for k, prefer in plan:
        if k in seen or k == kind:
            continue
        # one companion per ROLE: a cincture belt and a cincture rope are the
        # same girdle in two forms — whichever the hub has is enough
        if prefer and prefer in seen:
            continue
        rows = [r for r in idx.get(k, []) if r is not row and r.get("name") != row.get("name")
                and _kes(r) != float("inf")]
        hit = _pick(rows, prefer)
        if hit is not None:
            out.append(hit)
            seen.add(k)
            if prefer:
                seen.add(prefer)
        if len(out) >= limit:
            break
    return out


def _component_kinds(set_row: dict, catalog: list[dict]) -> list[str]:
    kinds: dict = {k: None for k in ()}
    kinds.update(_kinds_of(catalog))
    out: list[str] = []
    for piece in set_components(set_row, catalog):
        k = _piece_kind(piece, kinds) or (piece.split()[-1] if piece.split() else "")
        if k and k not in out:
            out.append(k)
    return out


def part_of_set(row: dict | None, catalog: list[dict] | None) -> dict | None:
    """The set this piece is also sold inside, when the hub has one: the set
    whose description lists the piece's kind and whose name shares the most
    with the piece's — "Cassock" → "Cassock Set" (the plainer name wins a tie,
    so the ladies' set never claims the plain cassock)."""
    if not row or not catalog or is_set_row(row):
        return None
    kind = product_kind(row)
    if not kind:
        return None
    mine = _tokens(row.get("name") or "")
    best, best_score = None, None
    for s in catalog:
        if not is_set_row(s) or _kes(s) == float("inf"):
            continue
        st = _tokens(s.get("name") or "")
        if kind not in st and kind not in _component_kinds(s, catalog):
            continue
        score = (len(mine & st), -len(st), -_kes(s))
        if best_score is None or score > best_score:
            best, best_score = s, score
    return best


def pieces_priced(set_row: dict | None, catalog: list[dict] | None) -> list[dict]:
    """Each piece a set lists, resolved to the hub row it is sold as alone:
    [{"piece": "straight collar shirt", "row": <hub row>}]. A piece with no
    row of its own (a lid, a basin) is left out — it has no price alone."""
    if not set_row or not catalog or not is_set_row(set_row):
        return []
    idx = _kinds_of(catalog)
    kinds: dict = dict(idx)
    head = product_kind({"name": (set_row.get("name") or "").replace("Set", "").replace("set", "")})
    prefs = {k: p for k, p in COMPANIONS.get(head, ())}
    out: list[dict] = []
    for piece in set_components(set_row, catalog):
        k = _piece_kind(piece, kinds)
        rows = [r for r in idx.get(k, []) if _kes(r) != float("inf")] if k else []
        hit = _pick(rows, prefs.get(k), like=piece)
        if hit is not None and all(o["row"] is not hit for o in out):
            out.append({"piece": piece, "row": hit})
    return out
