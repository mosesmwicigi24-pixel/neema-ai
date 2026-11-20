# Instruction enforcement audit

Started 2026-11-20 on the owner's directive "System-wide instruction enforcement audit and hardening". Status: **audit complete; no enforcement changed; nothing deployed.**

## Result

830 rules were extracted from every instruction given to the model. 62 are hard enforced.

| Status | Rules | Meaning |
|---|---|---|
| Instruction only | 393 | The model is told; nothing checks |
| Partially enforced | 241 | Checked on some routes or conditions only |
| Hard enforced | 62 | A guard prevents the outcome |
| Soft enforced | 56 | One rewrite is asked for, then it is sent |
| Conflicting | 45 | Contradicts another instruction or check |
| Observed only | 21 | Measured, not prevented |
| Not verified | 7 | Could not be established from this code |
| Not implemented | 5 | The capability the rule assumes does not exist |

By risk: 27 critical, 161 high, 299 medium, 343 low.

## Documents

| File | Deliverable |
|---|---|
| `A_RULE_INVENTORY.md`, `rule_inventory.jsonl` | A. Every rule, its ID, source and status |
| `B_UNENFORCED_RULES.md` | B. Everything not hard enforced |
| `C_RISK_FINDINGS.md` | C. Findings by risk, with examples |
| `D_COVERAGE_MATRIX.md` | D. Rules by domain and status; 40 outbound routes against each safeguard |
| `E_CONFLICT_REGISTER.md` | E. 22 conflicts with resolutions, then every conflicting rule |
| `H_DECISIONS.md` | H. Twelve decisions for management |
| F, G | Written when enforcement is built |

## Method

- The instruction file (`apps/api/app/agent/prompt.py`, 1,939 lines; instruction text ends at line 1903) was read line by line by four readers, one range each.
- A fifth reader read every instruction outside that file: per-turn notes, the comment instructions, tool descriptions and the guidance tools return, outreach briefs, staff-typed text that enters the instructions.
- A sixth traced every route by which text reaches a customer, from the low-level senders outwards.
- Each rule's status was set by reading the code that would enforce it. A model reviewer was not counted as enforcement. A test was not counted as enforcement.
- The lead auditor re-read the code for findings C1, C2, C3, C11, H1 and H4. The rest rest on one reader each and are marked "reported".

## Limits

- **One reader per range.** No second reader checked the others' classifications.
- **Duplicates are not merged.** The same requirement stated in several places appears as several rules; they are grouped under 40 canonical policies by wording match, read through for the critical and high groups only.
- **Nothing was executed.** Every finding is from reading code. None was reproduced against the running system or with the model.
- **Not accessible:** the hub's code and settings; the live server's settings (for example whether outreach is in shadow); live conversations; Meta's template approvals. Rules that depend on them are marked not verified.
- **The web and mobile apps were not audited**; they send staff-typed text, not Neema's.
