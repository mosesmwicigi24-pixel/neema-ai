"""The WhatsApp template registry — one place that knows what each approved
template is FOR, what it takes, and what the customer will read.

Why (audit, 2026-11-05): the same utility template was sent for three
different purposes with two different parameter contracts, a deciding
customer received a "time for the next round of supplies?" check-in about
"order sent" (the word after "order" in a free-text reason), and the inbox
stored "[template name] kind on number" instead of what the customer saw.

Rules enforced here, before Meta is ever called:
  · a purpose maps to exactly one configured template, or to None — a caller
    with no template for its purpose must hold for a person, never borrow one;
  · every body parameter is non-empty, free of placeholder residue ("{{", "None",
    "null") and, for an order-number slot, a real order number or a plain
    phrase — never a word scraped from a sentence;
  · the rendered body (the configured mirror of the approved text, with the
    parameters filled) is what the thread stores, tagged as a template.

Bodies mirror the templates approved in WhatsApp Manager (WA_EVENT_BODY,
WA_FOLLOWUP_BODY); when a body is not configured the stored text says so
plainly rather than inventing words the customer did not receive.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings

# A real order number: "ORD-1234", "#1234", "BH-00321", "1234" (3+ digits).
ORDER_NUMBER_RE = re.compile(r"^(?:#?[A-Z]{1,6}-?\d{1,8}|#?\d{3,10})$")
_RESIDUE_RE = re.compile(r"\{\{|\}\}|\{\d\}|\bNone\b|\bnull\b|\bundefined\b", re.IGNORECASE)


class TemplateRefused(ValueError):
    """The template cannot be sent as asked: wrong purpose, missing template,
    or a parameter that would read as nonsense to the customer."""


@dataclass(frozen=True)
class Template:
    name: str
    lang: str
    purpose: str            # order_update | care | replenishment | check_in | invite
    category: str           # utility | marketing
    slots: tuple[str, ...]  # named body slots, in {{1}}… order
    body: str               # mirror of the approved body with {1}{2}… placeholders

    def render(self, params: list[str]) -> str:
        if self.body:
            out = self.body
            for i, v in enumerate(params, start=1):
                out = out.replace("{" + str(i) + "}", v)
            return out
        # No mirror configured: say what went, honestly, without inventing text.
        filled = " · ".join(f"{slot}: {val}" for slot, val in zip(self.slots, params))
        return f"[WhatsApp template «{self.name}» sent] {filled}"


def _event_template(purpose: str) -> Template | None:
    if not settings.wa_event_template:
        return None
    return Template(name=settings.wa_event_template, lang=settings.wa_event_lang or "en",
                    purpose=purpose, category="utility",
                    slots=("first_name", "order_number", "status"),
                    body=getattr(settings, "wa_event_body", "") or "")


def for_purpose(purpose: str) -> Template | None:
    """The one template approved for this purpose, or None."""
    if purpose in ("order_update", "care", "replenishment"):
        # One approved utility template carries the three order-bound
        # purposes: an order status, the fit check on a delivered order, and
        # the supplies check-in the customer asked for on their last order.
        return _event_template(purpose)
    if purpose == "check_in":
        # A customer still DECIDING gets the follow-up template (it says we are
        # following up on their enquiry) — never the order/replenishment one.
        if not settings.wa_followup_template:
            return None
        return Template(name=settings.wa_followup_template,
                        lang=settings.wa_invite_lang or "en", purpose="check_in",
                        category="utility", slots=("first_name",),
                        body=(settings.wa_followup_body or "").replace("{first}", "{1}"))
    if purpose == "invite":
        if not settings.wa_invite_template:
            return None
        return Template(name=settings.wa_invite_template,
                        lang=settings.wa_invite_lang or "en", purpose="invite",
                        category="utility", slots=("first_name",), body="")
    return None


def validate_params(tpl: Template, params: list[str]) -> list[str]:
    """The parameters as they will be sent, or TemplateRefused."""
    if len(params) != len(tpl.slots):
        raise TemplateRefused(
            f"template {tpl.name} takes {len(tpl.slots)} parameter(s), got {len(params)}")
    out: list[str] = []
    for slot, raw in zip(tpl.slots, params):
        val = " ".join(str(raw if raw is not None else "").split())
        if not val:
            raise TemplateRefused(f"template {tpl.name}: empty {slot}")
        if _RESIDUE_RE.search(val):
            raise TemplateRefused(f"template {tpl.name}: unresolved {slot} ({val[:40]!r})")
        if slot == "order_number" and not (ORDER_NUMBER_RE.match(val) or val.startswith("your ")):
            # A real order number, or an honest plain phrase ("your order",
            # "your last order") — never a word scraped from a sentence.
            raise TemplateRefused(f"template {tpl.name}: {val!r} is not an order number")
        if len(val) > 1024:
            raise TemplateRefused(f"template {tpl.name}: {slot} too long")
        out.append(val)
    return out


def order_number_param(number: str | None, fallback: str = "your order") -> str:
    """An order-number slot value: the number when it is one, else the fallback."""
    n = " ".join(str(number or "").split())
    return n if n and ORDER_NUMBER_RE.match(n) else fallback


def first_name_param(name: str | None, fallback: str = "there") -> str:
    tok = ((name or "").strip().split() or [""])[0]
    tok = re.sub(r"[^\w'’-]", "", tok)
    return tok if 2 <= len(tok) <= 20 else fallback


async def send(wa_id: str, purpose: str, params: list[str]) -> tuple[str, str | None, Template]:
    """Validate, send, and return (rendered body, wamid, template). Raises
    TemplateRefused before any network call when the send would be wrong;
    the sender's own exceptions (SendOutcomeUnknown included) pass through."""
    from app.services import messaging as svc
    tpl = for_purpose(purpose)
    if tpl is None:
        raise TemplateRefused(f"no approved template for purpose {purpose!r}")
    clean = validate_params(tpl, params)
    resp = await svc.send_wa_template(wa_id, tpl.name, tpl.lang, clean)
    wamid = (((resp or {}).get("messages") or [{}])[0].get("id") or None)
    return tpl.render(clean), wamid, tpl


def meta(tpl: Template, params: list[str], **extra) -> dict:
    """raw_meta for the stored row: the thread shows the rendered body and
    knows it was a template (the inbox tags it)."""
    m = {"kind": "template", "template": tpl.name, "purpose": tpl.purpose,
         "lang": tpl.lang, "params": list(params)}
    m.update({k: v for k, v in extra.items() if v is not None})
    return m
