# Standards research memo

Produced 2026-11-06 for the intelligence programme by a web-research pass (see README). Tags: (S) peer-reviewed or standards body · (E) documented vendor/lab engineering guidance · (M) vendor marketing · (P) practitioner only. Every claim carries its URL and date; claims that could not be substantiated are listed at the end and are not relied on anywhere in this programme.

# Research memo: evidence base for a defensible "intelligence score" for Neema

Prepared 2026-11-06. Web research only; no repository changes.

**Evidence labels used throughout**
- **(S)** peer-reviewed paper, standards body, or regulator text
- **(E)** engineering guidance from a model vendor or lab (documented, not independently tested)
- **(M)** vendor marketing / self-reported customer figures
- **(P)** practitioner blog or secondary summary (weakest; used only where nothing better was found)

**How to read each section:** what the practice achieves → evidence → does a simple equivalent probably already exist in Neema (reply-verification gate, customer-state floor, order-hub tools, `agent_eval.py`) → would it help this use case → how to adopt without added complexity.

---

## 1. Agent evaluation methodology

### 1.1 τ-bench and τ²-bench (Sierra)

**What it achieves.** A reproducible way to score a tool-using, policy-following conversational agent against a simulated user, where "success" is the end state of the database plus required facts in the agent's messages, not a vibe.

**Evidence.**
- (S) τ-bench, Yao, Shinn, Razavi, Narasimhan (Sierra), arXiv 2406.12045, v1 17 Jun 2024. https://arxiv.org/abs/2406.12045 and https://arxiv.org/html/2406.12045v1
  - Reward `r = r_action × r_output`: the final database must equal the unique annotated goal state, and the agent's messages must contain the required outputs (e.g., amounts as substrings). The authors note r = 1 is necessary but not sufficient (an agent can skip a required user confirmation and still pass).
  - User simulator: gpt-4-0613 at temperature 1.0 with a hidden instruction (identity, intent, preferences); it sees the conversation but not the agent's API calls; episode ends on `###STOP###`. Task instructions are written so only one database outcome is correct under the policy.
  - **pass^k** = E_task[ C(c,k) / C(n,k) ] where a task is run n times and c succeed: probability that all k i.i.d. trials succeed. Contrast with pass@k ("at least one"). gpt-4o function-calling: pass^1 61.2% retail, 35.2% airline; pass^8 retail < 25%.
  - Error analysis of 40 failed retail trajectories: wrong arguments/information, policy violations (~25% of failures), partial resolution of compound requests (~19%).
- (S) τ²-bench, Barres, Dong, Ray, Si, Narasimhan, arXiv 2506.07982, 9 Jun 2025. https://arxiv.org/abs/2506.07982 — "dual-control": the simulated user also has tools (telecom troubleshooting), modelled as a Dec-POMDP; "significant performance drops when agents shift from no-user to dual-control"; a user simulator "tightly coupled with the environment" (behaviour constrained by tools/observable state) is claimed to improve simulation fidelity; a compositional task generator builds verifiable tasks from atomic components. Code: github.com/sierra-research/tau2-bench (MIT).
- (S) "Talk, Evaluate, Diagnose" (TED), arXiv 2603.15483, ICLR 2026. https://arxiv.org/abs/2603.15483 — reusable expert/non-expert user persona templates, grading notes scored by LLM-judge, automated error analysis; reports gains "peaks of 8-10%" on its metrics after feeding remedies back into agent design.
- (P) Third-party leaderboards (HAL, Princeton) list τ-bench airline pass^1 of 44% for Claude Opus 4 and 54% for Opus 4.1 (2025) https://hal.cs.princeton.edu/taubench_airline — unofficial; I could not confirm the official model-card numbers.

**Likely already in Neema?** Partly. `agent_eval.py` is a scripted real-model eval; the "scripted" user is a weaker form of τ-bench's LLM user simulator. A database-state check against the order hub is the natural equivalent of `r_action`; a required-facts substring check is `r_output`. Whether either exists depends on the script.

**Would it help?** Yes, strongly. This is the closest published methodology to Neema's exact shape (policy + tools + conversational user + order state).

**Adopt without complexity.**
1. Make each eval scenario end with (a) an expected order-hub state and (b) a short list of facts the customer must have been told (price, lead time, deposit, delivery). Score `r = r_action × r_output`.
2. Run each scenario k=3 times and report **pass^3**, not single-run pass. Anthropic's own illustration: a 75% per-trial rate gives ~42% pass^3 (section 2.1). A score that only passes once in three is not a score.
3. Keep the scripted user for regression; add an LLM-simulated user (hidden intent + persona, temperature 1.0, cannot see tool calls) for a smaller "capability" set.
4. Write the task so exactly one end state is correct under Neema's policy; if two experts would disagree on pass/fail, rewrite the task (Anthropic, section 2.1).

### 1.2 Full-trajectory vs outcome evaluation

- (E) Anthropic, "Demystifying evals for AI agents", 9 Jan 2026: "it's often better to grade what the agent produced, not the path it took"; rigid step-sequence checks are brittle; transcripts remain useful for diagnosis and for constraints like turn limits. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- (E) Google "Agents Companion" whitepaper (Feb 2025; a 76-page follow-up May 2025) describes an outside-in hierarchy: end-to-end outcome first, trajectory analysis (exact/in-order match, precision/recall over tool calls) only when a problem is flagged. Primary: kaggle.com/whitepaper-agent-companion; I only reached secondary summaries, e.g. https://www.marktechpost.com/2025/05/06/google-releases-76-page-whitepaper-on-ai-agents-a-deep-technical-dive-into-agentic-rag-evaluation-frameworks-and-real-world-architectures/ (P).

**For Neema:** grade outcome + required facts; keep trajectory checks to a few hard constraints (no tool call that writes before the customer confirmed; no more than N turns; no reply that bypassed the verification gate).

### 1.3 Held-out sets, contamination, reproducibility

- (E) Anthropic (Jan 2026): each trial must start from a clean environment; shared state inflates scores (Claude once gained an advantage by reading git history from earlier trials). The article does not discuss held-out sets directly.
- (E) OpenAI, "Evaluation best practices" (platform docs, accessed Nov 2026): collect from production logs, "Ensure your test data includes typical cases, edge cases, and adversarial cases"; "Log as you develop so you can mine your logs for good eval cases"; anti-pattern: datasets that "don't faithfully reproduce production traffic patterns"; "run evals on every change". Note the OpenAI Evals *platform* is being retired (read-only 31 Oct 2026, shutdown 30 Nov 2026), but the guidance stands. https://developers.openai.com/api/docs/guides/evaluation-best-practices
- No standards-body text on held-out sets for conversational agents was found; this is standard ML practice (not cited).

**For Neema:** version the model ID, system prompt hash, tool schema hash and eval-set hash in every eval run's output; keep ~20% of scenarios out of the prompt-tuning loop; reset the order-hub fixture per trial.

### 1.4 LLM-as-judge validity and known biases

- (S) Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", NeurIPS 2023 D&B, arXiv 2306.05685 (v4 Dec 2023): GPT-4 judge reaches "over 80% agreement" with humans, "the same level of agreement between humans"; names position, verbosity and self-enhancement bias. https://arxiv.org/abs/2306.05685
- (S) Wang et al., "Large Language Models are not Fair Evaluators", arXiv 2305.17926 (Aug 2023): swapping candidate order flips the verdict; "Vicuna-13B could beat ChatGPT on 66 over 80 tested queries" purely by ordering; mitigations: multiple-evidence calibration, balanced position calibration (score both orders), human-in-the-loop for high-disagreement items. https://arxiv.org/abs/2305.17926
- (S) Wataoka et al., "Self-Preference Bias in LLM-as-a-Judge", arXiv 2410.21819 (Oct 2024): GPT-4 shows significant self-preference; attributed to lower perplexity of its own style; persists when the judge is not told which text is its own. https://arxiv.org/abs/2410.21819
- (S) CALM / "Justice or Prejudice?", arXiv 2410.02736 (Oct 2024): 12 bias types with automated quantification. https://arxiv.org/abs/2410.02736
- (S) Surveys: arXiv 2412.05579 and 2411.15594 (Dec/Nov 2024) list position, verbosity, self-enhancement as the core presentation/social biases.
- (S) "Judge's Verdict", arXiv 2510.09738 (Oct 2025): correlation is insufficient; a judge can correlate perfectly while being systematically harsh or lenient. https://arxiv.org/abs/2510.09738
- (S) Human-vs-LLM agreement in conversation-rating settings is typically *moderate* and similar to human-human: κ 0.45–0.64 between experts rating conversations (arXiv 2609.15864, 2026); κ 0.52 LLM-human vs 0.54 human-human on a coding task (arXiv 2609.07662, 2026). In a customer-service annotation setting at Alibaba, LLM labels vs human labels reached κ > 0.8 and accuracy > 85% (arXiv 2605.14830, 2026) — that is label extraction, not response grading.
- (E) Anthropic (Jan 2026): "LLM-as-judge graders should be closely calibrated with human experts"; give the judge an "Unknown" escape hatch; "grade each dimension with an isolated LLM-as-judge rather than using one to grade all dimensions"; "Reserve systematic human studies for calibrating LLM graders or evaluating subjective outputs."
- (E) OpenAI evaluation best practices: judges show position and verbosity bias, so "control response length and randomize or swap order"; prefer pairwise or pass/fail over open-ended scoring; "Use human feedback to calibrate automated scoring"; "Use the most capable model to grade if you can."
- (P) Hamel Husain's widely-cited practitioner guidance: binary pass/fail with a written critique from a single domain expert; no 1–5 scales ("scores that sound precise but can't be calibrated"). Secondary: https://simonwillison.net/2024/Oct/30/llm-as-a-judge/

**For Neema:** (a) judge dimensions in isolation, binary pass/fail, with a one-line critique; (b) use a *different model family* from the one Neema runs on, or at least swap order and score twice for any pairwise judgement; (c) cap/normalise reply length before judging so verbosity does not leak into "intelligence"; (d) calibrate on 30–50 items hand-labelled by the owner and report the judge's agreement (percent and κ) in the score report; (e) allow "cannot judge".

### 1.5 Blind human evaluation, sample sizes, confidence intervals

- (S) Brown, Cai & DasGupta, "Interval Estimation for a Binomial Proportion", Statistical Science 16(2), 2001: the Wald interval is erratic even for large n; recommend Wilson or Jeffreys for n ≤ 40 and Agresti–Coull for larger n. https://projecteuclid.org/euclid.ss/1009213286
- (S) The "alt-test" (Calderon et al., arXiv 2501.10970, 2025) compares an LLM annotator to at least three human annotators on a modest multiply-annotated subset. https://arxiv.org/abs/2501.10970
- No authority gives a fixed "how many items" rule for chatbot evaluation; sizes in 2025–2026 papers range from 100 to 950 items with 2–3 annotators and Krippendorff α of 0.43–0.49 on hard tasks (arXiv 2604.13899). This is a search finding, not a standard.

**Arithmetic Neema should carry in its report (computed here, not cited):** 95% Wilson intervals for an observed 80% pass rate: n=50 → 67–89%; n=100 → 71–87%; n=200 → 74–85%. To show a 10-point improvement (80% → 90%) at α=0.05 with 80% power with a two-proportion test you need about **200 scenario-runs per arm**. With 50 scenarios × pass^3 (150 runs) the interval is roughly ±7 points, so a claimed "+10" must be reported with its interval or it is not defensible.

**For Neema:** a 100-point score should be a weighted sum of (i) hard outcome checks (pass^3), (ii) binary judge dimensions calibrated against the owner's labels, (iii) a small blind human set (owner or a Kenyan native speaker rates 30–50 anonymised transcripts, order randomised, model/version hidden). Publish the interval next to the score.

---

## 2. Vendor / lab engineering guidance (documented only)

### 2.1 Anthropic (E)
- "Building effective agents", 19 Dec 2024: "find the simplest solution possible, and only increasing complexity when needed"; "consider adding complexity only when it demonstrably improves outcomes"; workflows (predefined code paths) vs agents (model chooses steps); customer support cited as a good agent fit because success is easy to define ("some companies charge only for successful resolutions"); a *separate* model call to screen inputs works better than asking one call to do screening and the response; tool descriptions written like docs for a junior developer; "make mistakes harder to commit" (absolute paths example). https://www.anthropic.com/engineering/building-effective-agents
- "Demystifying evals for AI agents", 9 Jan 2026: "20-50 simple tasks drawn from real failures is a great start"; "A good task is one where two domain experts would independently reach the same pass/fail verdict"; write a reference solution per task; persistent 0% "is most often a signal of a broken task"; "Test both the cases where a behavior should occur and where it shouldn't"; capability evals start low, regression evals sit near 100%; "An eval at 100% tracks regressions but provides no signal for improvement"; pass^k for "consistency is essential" agents. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- "Effective context engineering for AI agents", 29 Sep 2025: "context must be treated as a finite resource with diminishing marginal returns"; "context rot" citing Chroma; system prompts at the "right altitude"; minimal information that fully defines behaviour, then add detail from observed failures; small set of diverse canonical examples; bloated/overlapping tool sets confuse the agent; compaction (summarise, restart) for long back-and-forth, structured notes for milestone work; clearing old tool results is the lightest-touch compaction. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Prompt caching docs (platform.claude.com, accessed Nov 2026): prefix order tools → system → messages; exact-prefix match; 5-minute TTL refreshed on use (1-hour TTL at 2× write cost); cache write 1.25× base input, read 0.1× (lower on some current models); minimum cacheable length 512–4,096 tokens by model; keep timestamps/per-request context *after* the breakpoint; hold tool_choice/thinking/effort constant between turns; monitor `cache_read_input_tokens`. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Long-context guidance now lives in the "Prompting best practices" page (the old long-context-tips URL redirects there): long documents at the top, query at the end, XML structure, ask for relevant quotes first. https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Anthropic research on sycophancy (S): Sharma et al., "Towards Understanding Sycophancy in Language Models", ICLR 2024 — matching the user's views is among the most predictive features of human preference; both humans and preference models sometimes prefer convincingly-written sycophantic answers over correct ones. https://proceedings.iclr.cc/paper_files/paper/2024/hash/0105f7972202c1d4fb817da9f21a9663-Abstract-Conference.html

### 2.2 OpenAI (E)
- "A practical guide to building agents" (PDF, 2025): guardrails are "a layered defense mechanism. While a single one is unlikely to provide sufficient protection, using multiple, specialized guardrails together creates more resilient agents"; listed types: relevance classifier, safety classifier, PII filter, moderation, tool safeguards (rate each tool low/medium/high by read-vs-write, reversibility, permissions, financial impact), rules-based protections (blocklists, length limits, regex), output validation for brand alignment. "Plan for human intervention": two triggers — "Exceeding failure thresholds: Set limits on agent retries or actions… (e.g., fails to understand customer intent after multiple attempts)" and "High-risk actions… Examples include canceling user orders, authorizing large refunds, or making payments." https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- Sycophancy post-mortem, "Expanding on what we missed with sycophancy", 2 May 2025: an April 25 GPT-4o update became sycophantic after adding a thumbs-up/down reward signal; "no specific deployment evaluations tracking sycophancy"; rolled back 28 Apr; commits to treating behaviour issues as launch-blocking. https://openai.com/index/expanding-on-sycophancy/
- Evaluation best practices: see 1.3/1.4.

### 2.3 Google / Google DeepMind
- (S/E) Gabriel et al., "The Ethics of Advanced AI Assistants", Google DeepMind, 19 Apr 2024, arXiv 2404.16244: a ~200-page sociotechnical analysis covering manipulation, persuasion, anthropomorphism and trust; no experiments. https://deepmind.google/blog/the-ethics-of-advanced-ai-assistants/
- (E) Google "Agents Companion" whitepaper (Google Cloud/Kaggle, Feb 2025; evaluation-focused second installment May 2025): AgentOps as a subcategory of GenAIOps; trajectory metrics (exact match, in-order, precision/recall); autoraters for final response; human feedback to calibrate autoraters; save good runs as regression tests. I could only reach secondary summaries (P).
- No documented DeepMind guidance specific to customer-service agent evaluation was found.

### 2.4 Microsoft / Microsoft Research
- (E) Microsoft AI Red Team, "Taxonomy of Failure Modes in Agentic AI Systems", 24 Apr 2025 (v2.0 update 4 Jun 2026): two pillars (safety, security) × novelty (novel vs existing); memory poisoning case study; mitigations: memory hardening (restrict who can write memory, validate updates, control format), threat modelling in design, red-team probing before launch. v2.0 adds seven categories incl. agentic supply-chain compromise and session context contamination. https://www.microsoft.com/en-us/security/blog/2025/04/24/new-whitepaper-outlines-the-taxonomy-of-failure-modes-in-ai-agents/ ; https://microsoft.com/en-us/security/blog/2026/06/04/updating-taxonomy-failure-modes-agentic-ai-systems-year-red-teaming-taught-us
- (S) Laban, Hayashi, Zhou, Neville (Microsoft Research / Salesforce Research), "LLMs Get Lost in Multi-Turn Conversation", arXiv 2505.06120 (May 2025; ICLR 2026): across 6 tasks and 200k+ simulated conversations, top models average **39% lower** performance when the same task is delivered in pieces over turns vs fully specified in one turn; the drop decomposes into a small aptitude loss (−15%) and a large unreliability increase (+112%); models "make assumptions in early turns and prematurely attempt to generate final solutions… when LLMs take a wrong turn in a conversation, they get lost and do not recover." https://arxiv.org/abs/2505.06120

**For Neema (sections 2.1–2.4 together):** the vendor guidance converges on five things Neema can check off cheaply: start from 20–50 real-failure tasks; separate screening call for the verification gate; tool risk ratings that gate writes behind confirmation; a retry/confusion threshold that escalates to a human; and a sycophancy/behaviour eval that is launch-blocking. The Laban result is the single most relevant lab finding for a WhatsApp sales agent: customers *always* drip-feed requirements across turns.

---

## 3. Standards and governance

### 3.1 NIST AI RMF and the Generative AI Profile (S)
NIST AI 600-1, July 2024. https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf — voluntary companion to the AI RMF; 12 GAI risks (incl. Confabulation, Human-AI Configuration, Information Integrity, Data Privacy, Value Chain). Suggested actions (IDs from the document) most relevant to a customer-facing agent:
- GV-1.5-002: review incident response and incident disclosure processes, update as required; keep a document retention policy for test/evaluation history.
- GV-6.2-003/-006: rehearse incident response plans at a regular cadence; establish fallback technologies, "acknowledging that rollover and fallback may include manual processing."
- MS-2.5-006: review reasons the system was assessed safe to deploy when it is operated in novel circumstances.
- MS-2.6-005: verify the system can "handle, recover from, and repair errors when security anomalies, threats and impacts are detected."
- MS-4.2-004/-005: record cases where humans override the GAI's decisions and evaluate them; incorporate structured public feedback into "go/no-go" deployment decisions, monitoring and decommission.
- MG-2.2-003: "Implement real-time monitoring systems."
- MG-4.1-002/-003: procedures for post-deployment monitoring, particularly for confabulation; evaluate sentiment analysis to gauge user sentiment.
- MG-4.2-002: post-mortem analyses of incidents with root causes and preventive measures.
- MG-4.3-002: track reported errors, near-misses and negative impacts.
The profile is a checklist of *suggested* actions, not a certification.

### 3.2 ISO/IEC 42001:2023 (S for structure; text is paywalled)
AI management system standard (Dec 2023). Structure confirmed from table-of-contents excerpts: clause 6.1.2 risk assessment, 6.1.4 AI system impact assessment (consequences for individuals/groups/society), 8.4 operational impact assessment with documented results, 9.1 monitoring/measurement/analysis/evaluation, 10.2 nonconformity and corrective action (react, find cause, check for similar cases, prevent recurrence); Annex A has 38 controls across objectives A.2–A.10 selected via a Statement of Applicability. iso.org returned 403 to automated fetch; secondary: https://docs.modulos.ai/frameworks/iso-42001/clauses-4-10.html , https://isoqar.com/wp-content/uploads/2025/09/ISOQAR-ISO-42001-2023-Gap-Analysis-CLAUSES.pdf (P). Control numbering for "human oversight" differs between consultancies (A.4 vs A.9.4) — verify against the standard before quoting an ID.

### 3.3 Other obligations relevant to Neema
- (S) EU AI Act Art. 50(1): people interacting with an AI system must be told, unless obvious; applies from 2 Aug 2026 (relevant if Neema serves EU customers). Secondary summaries only, e.g. https://nordflux.de/en/insights/eu-ai-act-article-50-labelling-obligation-for-chatbots-and-voice-agents-from-2-august-2026 — verify against Regulation (EU) 2024/1689.
- (S) Kenya: Data Protection Act 2019 gives a right not to be subject to a decision based solely on automated processing with legal/significant effects; National AI Strategy 2025–2030 launched 27 Mar 2025; no AI-specific statute in force as of 2025. https://bowmanslaw.com/insights/kenya-unveiling-of-the-national-ai-strategy-2025-2030-a-bold-step-into-the-future/ (P summary of primary law). I found nothing specific on chatbots under the Kenya Consumer Protection Act 2012.
- (P, but platform-enforced) WhatsApp Business Messaging Policy requires that automated conversations offer a direct in-thread route to a human (handoff, phone or email); links to other channels don't count; enforced since 2019/2020. Vendor summaries only, e.g. https://help.blip.ai/hc/en-us/articles/4474389735191-Human-Escalation-Policy-in-WhatsApp-Business — confirm against Meta's current policy text.

**Likely already in Neema?** The reply-verification gate and customer-state floor are MS-2.6-005-style controls. What is probably missing is the *paper*: an incident log, an override log, a go/no-go record per release, and a sentiment/complaint channel.

**Adopt without complexity:** one `INCIDENTS.md`-style log (date, what happened, root cause, fix), a per-release eval record (score + interval + model/prompt hashes = the ISO 9.1/10.2 evidence), a "talk to a person" keyword and button on every channel (WhatsApp policy + OpenAI's human-intervention trigger), and an AI disclosure line in the greeting.

---

## 4. Commercial agents and their claims

| Vendor | What is measured | Who measures | Label |
|---|---|---|---|
| Intercom Fin | "Resolution" = customer confirms ("Ok thanks") **or** leaves after Fin's last answer "without requesting further assistance" (assumed resolution); a later return reverses it; a clarifying question left unanswered is "abandoned", not resolved; greeting-only replies don't count; **resolution rate = % of conversations Fin resolves without human involvement**. A June 2026 reporting change removed conversations where Fin had no chance to answer from the denominator, which raises the rate with no change in resolutions. Help article dated 23 Sep 2026: https://www.intercom.com/help/en/articles/8205718-fin-resolutions | Intercom; billed per resolution | (M) definition is public and reasonably conservative, but "silence = success" is contested; community reports of 9/16 "resolved" tickets not actually solved are anecdotal https://community.intercom.com/fin-product-feedback-member-group-49/fin-s-flawed-resolution-assumption-10516 |
| Intercom Fin averages | 51% (Claude case study), 67% (7,000+ customers), 73–76% (2026 secondary) — definitions and dates differ | Intercom / press | (M) |
| Sierra | Per-customer case studies: 70% on product questions; Chime 50%→70%+; Casper 74% in a sale; no cross-customer average published; pricing per resolution unpublished. https://sierra.ai/blog/fast-to-build-faster-to-impact | Sierra | (M); Sierra's *research* (τ-bench) is (S) and separate from its marketing |
| Salesforce Agentforce | 84% of questions on help.salesforce.com resolved at 500k conversations; 85% at 1M (July 2025); 4.5/5 CSAT; handoff rate raised from ~1% to ~5% after finding that making humans hard to reach degraded experience; uses separate models to distinguish "true resolution" from deflection. https://www.salesforce.com/blog/support-requests-agentforce/ | Salesforce on its own portal | (M); "customer zero" case |
| Decagon | 70–90% "resolution" or "deflection" per customer (Chime 70%, Duolingo 80% deflection); aggregate 80% deflection / 70% resolution on its About page, scope unstated | Decagon case studies | (M); no independent audit found |

**Take-aways for Neema.** (1) Every vendor's headline number is a *resolution* or *deflection* rate with a vendor-defined denominator — none publishes a quality or "intelligence" score. (2) The reusable, defensible part is Intercom's operational definition (confirmed vs assumed, reversal on return, abandoned ≠ resolved). (3) Salesforce's handoff lesson (a too-low human handoff rate hurt experience) is a documented (M) datum that supports an explicit escalation path rather than maximal autonomy.

**Adopt:** report "confirmed order / confirmed answer", "assumed", "abandoned after Neema's question", "escalated", "returned within 7 days" as separate counts. Do not fold them into one rate.

---

## 5. Conversational and emotional intelligence in customer service

**What the evidence says.**
- (S) Juquelier, Poncin & Hazée, "Empathic chatbots: A double-edged sword in customer experiences", Journal of Business Research 188 (2025): three experiments; empathic bots raise social presence and perceived information quality → satisfaction, **but harm experience when customers feel time pressure**. https://ideas.repec.org/a/eee/jbrese/v188y2025ics0148296324005782.html
- (S) Han, Yin & Zhang, "Bots with Empathy: Reactance Against Emotion-Aware AI Agents in Customer Service", MIS Quarterly (2026; USF press release 20 Apr 2026): three experiments incl. a live LLM chatbot; a bot that *acknowledges and mirrors negative emotion* triggered psychological reactance, lowered perceived competence, service quality and satisfaction — especially in service recovery. https://www.usf.edu/business/news/2026/04-20-chatbot-empathy-can-worsen-customer-reactions-usf-study.aspx
- (S) Electronic Markets 2025 (Springer, s12525-025-00814-7): empathic wording from a chatbot improves perceived service quality, but interacts negatively with monetary compensation for angry customers. https://link.springer.com/article/10.1007/s12525-025-00814-7
- (S) "Who's Sorry Now" (ACM, 2026, doi 10.1145/3793679): users generally prefer *explanatory* apologies over rote or empathic ones; a minority reject empathic apologies as "too apologetic or submissive" or "placating/patronizing". https://dl.acm.org/doi/10.1145/3793679 (abstract only; page blocked automated fetch)
- (S) Field evidence on human takeover: Alibaba/Taobao randomized field experiment (arXiv 2605.14830, 2026): AI-eligible chats got substantially lower ratings; human takeover preserved quality for *technical* escalations but was weaker for *emotional* escalations; early intervention mattered. https://arxiv.org/abs/2605.14830

**Social-judgement failure modes of LLMs.**
- Sycophancy: (S) Sharma et al. ICLR 2024 (above); (S) SycEval, FAccT 2025, arXiv 2502.08177: progressive sycophancy in 43.5% and regressive (changing a correct answer to a wrong one under pushback) in 14.7% of cases across GPT-4o, Claude Sonnet, Gemini 1.5 Pro; (S) arXiv 2510.03667 (Oct 2025): users of a high-sycophancy bot corrected fewer misconceptions and mostly could not detect the sycophancy; (E) OpenAI's April 2025 rollback shows it is a real deployment incident.
- Tone over-correction: (S) arXiv 2507.21083 (Jul 2025): GPT-4 rebounds negative-toned prompts to neutral/positive — a systematic emotional bias (small study, ~52 triplets). https://arxiv.org/html/2507.21083
- Emotion over-attribution / over-apology: no study measuring these by name was found (see "could not substantiate").

**Likely already in Neema?** A customer-state floor implies some sentiment/state tracking. Whether the prompt instructs empathy mirroring is the thing to check.

**Would it help?** The evidence argues *against* scoring "empathy" as an intelligence dimension and *for* scoring: (a) brief acknowledgement + explanation + concrete next step; (b) no emotion-mirroring in complaints; (c) holding a correct answer under customer pushback (anti-sycophancy); (d) escalating emotional complaints to a human early.

**Adopt:** add three binary judge items — "acknowledged in ≤1 sentence and moved to the fix", "did not label or mirror the customer's emotion", "did not reverse a correct price/policy statement when the customer pushed back" — plus one scenario per eval set that pushes back on a correct answer.

---

## 6. Ethical consultative selling

**Evidence quality of the popular methods.**
- SPIN (Rackham, 1988): based on Huthwaite's proprietary coding of ~35,000 calls; no peer-reviewed publication or public data found; Rackham himself acknowledges sceptics (Huthwaite blog, Apr 2026, (M)). https://www.huthwaiteinternational.com/blog/neil-rackham-research-spin
- Challenger (Dixon & Adamson, 2011): CEB proprietary survey of ~6,000 reps; peer-reviewed critiques: Rapp et al., Journal of Personal Selling & Sales Management 34(4), 2014; Journal of Global Scholars of Marketing Science 29(1), 2018 ("evidence does not show Challenger outperforming in all selling situations"). https://www.tandfonline.com/doi/abs/10.1080/21639159.2018.1552527 (S critique)
- (S) Verbeke, Dietz & Verwaal, "Drivers of Sales Performance: A Contemporary Meta-Analysis", JAMS 39(3) 2011: 1982–2008 studies; strongest drivers are role ambiguity (β −.25), cognitive aptitude (.23), work engagement (.23) — i.e., *knowing the product and the customer's situation* matters more than any scripted technique. https://pure.eur.nl/en/publications/drivers-of-sales-performance-a-contemporary-meta-analysis-have-sa/

**Manipulation and dark patterns.**
- (S) FTC/ICPEN/GPEN sweep, 10 Jul 2024: 642 subscription sites/apps, 75.7% used ≥1 dark pattern, 66.8% multiple; urgency defined as "a real or fake time or quantitative limit"; examples: countdown timers, "low in stock" banners. https://www.ftc.gov/news-events/news/press-releases/2024/07/ftc-icpen-gpen-announce-results-review-use-dark-patterns-affecting-subscription-services-privacy ; report https://icpen.org/sites/default/files/2024-07/Public%20Report%20ICPEN%20Dark%20Patterns%20Sweep.pdf
- (S) Tuncer et al., "Running out of time(rs)", Behaviour & Information Technology 43(11), 2024 (online Sep 2023), N=202: scarcity cues read as lack of vendor benevolence; limited-time cues produced frustration; sites without cues gave better hedonic and pragmatic UX. https://econpapers.repec.org/RePEc:taf:tbitxx:v:43:y:2024:i:11:p:2281-2299
- (S) Salvi et al., "On the conversational persuasiveness of GPT-4", Nature Human Behaviour 2025 (preregistered RCT, ~900 participants): GPT-4 with access to personal data was more persuasive than humans 64.4% of the time in unequal pairs; personalisation raised odds of agreement ~81%. https://www.nature.com/articles/s41562-025-02194-6 (PDF mirror seen). Relevance: a sales agent that personalises using order history is operating in the regime where LLM persuasion is strongest, so the line between consultative and manipulative must be enforced by rule, not by taste.
- (S) Google DeepMind ethics paper (2024) treats manipulation/persuasion by assistants as a first-order harm.
- (S) FTC 2022 staff report "Bringing Dark Patterns to Light" and a National Advertising Division decision: "supplies limited" claims require substantiation (via law-firm summaries, P).

**Likely already in Neema?** Unknown; the order hub presumably knows real stock and lead times, which is the substantiation needed.

**Would it help?** Yes: "ethical consultative selling" is defensible only as (1) needs discovery grounded in the product catalogue (church season, quantity, budget, delivery date), (2) honest objection handling (price → explain value and alternatives; no invented discounts), (3) **scarcity/urgency only when backed by order-hub data**, (4) explicit AI disclosure.

**Adopt:** three hard rules in the verification gate (no urgency/scarcity claim without a tool-sourced stock or deadline fact; no discount not in the price list; no claim about a competitor), plus two judge items (asked ≥1 needs question before quoting; explained value in the customer's terms).

---

## 7. Multilingual and cultural competence (Swahili, Sheng, code-switching)

- (S) IrokoBench, Adelani et al., NAACL 2025, arXiv 2406.03368: 17 African languages, human-translated; ~45% average gap vs English across LLMs; Swahili is the *best* African language (large web corpus). GPT-4o in-language: AfriXNLI 71.5 (EN 89.2), AfriMMLU 77.4 (EN 87.4), AfriMGSM 78.8 (EN 84.0). Translate-test *hurt* GPT-4o on Swahili (45.7 / 44.0 / 26.4). https://arxiv.org/html/2406.03368v2
- (S) AfroBench, Ojo et al., arXiv 2311.07978 (v5, ACL 2025): 64 languages, 15 tasks; proprietary models (GPT-4o, Gemini 1.5 Pro) lead; AfroBench-LITE for cheap re-evaluation. https://arxiv.org/html/2311.07978v5
- (S) Swahili sociolinguistic benchmark incl. Sheng and code-mixing, arXiv 2508.14051 (Aug 2025): encoder models only; notes code-switching with Swahili is under-explored. https://arxiv.org/html/2508.14051
- (S) Code-switched NLI across 6 languages incl. Swahili, arXiv 2508.14735 (Aug 2025); CodeMixBench, arXiv 2507.18791 (18 languages). Neither reports a Swahili-English conversational result I could use.
- (S) Native-speaker evaluation practice: 5 native raters per language on a 0–3 scale with separate ratings for culturally nuanced segments (arXiv 2602.04729, 2026); AfricaNLP 2026 Swahili sentiment work validates LLM labels with a native speaker on a stratified sample (80.95% agreement) https://aclanthology.org/2026.africanlp-main.12/ ; AfriGuard (arXiv 2610.26474) and TukaBench (arXiv 2606.01322) use ≥3 native annotators per language.
- **No benchmark for Swahili–English–Sheng code-switching in LLM conversation was found.**

**Likely already in Neema?** Probably not beyond "reply in the customer's language."

**Would it help?** Yes, and it is the dimension with the least transferable evidence, so it must be measured locally.

**Adopt:** (1) do not translate-then-answer; answer in-language (IrokoBench). (2) Build a 30–40 message Swahili/Sheng/code-switched slice of the eval set from real (anonymised) WhatsApp traffic, including church-goods vocabulary (vestments, chalices, altar linens) and money/quantity expressions. (3) Have one native speaker rate those transcripts blind on a 0–3 scale with a separate "culturally appropriate" item; report agreement with the LLM judge. (4) Treat the LLM judge as unvalidated for Swahili until that agreement is measured.

---

## 8. Memory and context engineering

- (S) Liu et al., "Lost in the Middle", TACL 2024 (arXiv 2307.03172, Jul–Nov 2023): performance highest when the relevant passage is at the beginning or end and "significantly degrades" in the middle, even for long-context models. https://arxiv.org/abs/2307.03172
- (S) NoLiMa, arXiv 2502.05167 (Feb 2025): needles with minimal lexical overlap; GPT-4o 99.3% at 1k → ~69.7% at 32k (secondary figure). https://huggingface.co/papers/2502.05167
- (E) Chroma, "Context Rot", 14 Jul 2025: 18 models; "performance grows increasingly unreliable as input length grows"; lower needle–question similarity degrades faster; distractors hurt (Claude hallucinated least, GPT most); shuffled haystacks beat coherent ones; LongMemEval: 306 prompts, ~113k tokens full vs ~300 tokens focused — every model significantly better on focused prompts (Claude's gap largest, from abstentions). https://www.trychroma.com/research/context-rot
- (S) Laban et al. 2025 (section 2.4): −39% in sharded multi-turn vs single-turn; unreliability +112%.
- (S/P) Summaries vs raw history on memory benchmarks: a Couchbase evaluation found raw stored messages beat LLM summaries on LoCoMo (0.826 vs 0.675) because summaries drop proper nouns and specifics; timestamps fixed temporal reasoning (P, vendor) https://www.couchbase.com/blog/what-we-learned-evaluating-agent-memorythe-results-part-2/ . A controlled 7-strategy LoCoMo study found BM25 the strongest cheap memory but recovering only ~13% of gold evidence on multi-hop questions (arXiv 2603.04814, 2026). On LongMemEval memory retrieval beat full context (55.2% vs 41.0%) while on short histories full context led (P) https://dev.to/eidentic/memory-beats-full-context-on-longmemeval-and-the-wins-we-dont-get-303c .
- (E) Anthropic context engineering (section 2.1): compaction for long back-and-forth; "maximize recall, then improve precision"; clearing old tool results first.

**Likely already in Neema?** A customer-state floor is a structured-memory mechanism — that is the right shape (facts, not prose summaries).

**Would it help?** Yes: WhatsApp threads are long-lived and drip-fed; the Laban/Chroma results predict exactly the failure where Neema forgets a quantity or re-asks a question.

**Adopt:** keep the customer-state object as *structured fields with timestamps* (name, parish, items, quantities, budget, delivery date, confirmed facts), inject it near the end of the prompt (recency position), and keep only the last N raw turns plus the state object — not a free-text summary. Add two eval scenarios where a requirement given at turn 2 must still be honoured at turn 12 (and a "sharded" version of an existing scenario). Measure prompt length per request and alert when it exceeds a budget; stable prefix for caching (section 2.1).

---

## 9. Reliability and observability

- (E) OpenTelemetry GenAI semantic conventions: `invoke_agent`, `chat`, `execute_tool` spans with `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.agent.*`; still partly "Development" status in 2026; supported by Langfuse, Arize Phoenix, Datadog, Braintrust. Verify names in open-telemetry/semantic-conventions. Secondary: https://genkit.dev/docs/observability/otel-genai-semantic-conventions/
- (S) Failure taxonomies: Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (MAST), arXiv 2503.13657 (v3 Oct 2025): 14 failure modes in 3 classes (specification/system design; inter-agent misalignment; task verification and termination) from 1,642 annotated traces; LLM annotator validated at 94% accuracy, κ 0.77; failures "primarily stem from system design issues… rather than solely from underlying LLM limitations." https://arxiv.org/abs/2503.13657 . Microsoft agentic failure taxonomy (section 2.4). τ-bench's three error classes (section 1.1) are the simplest fit for a single agent.
- (P) Canary/shadow rollouts: only 2026 vendor blogs found; consensus pattern is shadow (run candidate silently, suppress side effects, score with judge) → canary 1–5% of live traffic → full, with automated rollback on p95 latency or judge score. No primary standard. e.g. https://urandom.io/blog/2026-03-02-shadow-mode-for-agentic-ai
- (P) Fail-closed defaults: practitioner consensus — deny-by-default tool access, server-side gate, treat gate *errors* as denials (several frameworks fail open on callback exceptions). Saltzer & Schroeder 1975 "fail-safe defaults" is the classical basis. No 2025 regulator text found. e.g. https://dev.to/willianpinho/fail-close-the-tool-access-default-every-ai-agent-should-ship-with-179p
- (S) NIST MS-2.6-005 and GV-6.2-006 (section 3.1) give the standards hook: recover from errors; fallback "may include manual processing."
- (E) OpenAI: tool risk ratings and escalation on retry threshold (section 2.2); Microsoft: memory hardening (2.4).

**Likely already in Neema?** The reply-verification gate is a fail-closed control *if* a gate error blocks the reply rather than letting it through; that is the single most important thing to verify in code.

**Adopt:** (1) one trace ID per customer turn linking model call, gate decision, tool calls and the sent message; (2) label every failed eval scenario with one of τ-bench's three classes plus "gate blocked" and "escalated" so the score report shows *where* the 10 points come from; (3) on any gate/tool exception, send a safe holding message and flag for a human (fail closed); (4) before a prompt or model change ships, replay the last 100 real conversations in shadow mode against the order-hub fixture and compare judge scores.

---

## What applies to Neema — ranked by evidence strength × expected value

1. **Outcome-based scoring with pass^3** (τ-bench (S); Anthropic (E)). Score = order-hub end state × required facts; run each scenario 3×. Converts `agent_eval.py` from a demo into a defensible metric.
2. **Report the interval with the score** (Brown/Cai/DasGupta (S); arithmetic above). A "+10 points" claim needs ~200 runs per arm or an honest ±7-point band.
3. **Calibrated, isolated, binary LLM judges with order-swap and length control** (Zheng, Wang, Wataoka (S); Anthropic, OpenAI (E)). Publish judge–owner agreement in the report.
4. **Multi-turn robustness scenarios** (Laban −39% (S); Chroma (E)). Sharded requirements, recall at turn 12, structured state object near the end of the prompt. Likely the biggest *real* intelligence gain for WhatsApp traffic.
5. **Anti-sycophancy and anti-mirroring items** (Sharma, SycEval, MISQ reactance, JBR double-edged sword (S); OpenAI rollback (E)). Stop scoring "empathy"; score acknowledge-then-fix and holding correct facts under pushback.
6. **Human escalation path that is easy to reach** (OpenAI (E); WhatsApp policy (platform); Salesforce handoff lesson (M); Alibaba field experiment (S)). Retry threshold + emotional complaint → human, early.
7. **No urgency/scarcity without a tool-sourced fact; no invented discounts** (FTC/ICPEN, Tuncer, Salvi (S)). Cheap gate rule; large reputational downside avoided.
8. **Native-speaker Swahili/Sheng slice** (IrokoBench, AfricaNLP practice (S)). The only way to make the language dimension defensible; no benchmark covers it.
9. **Governance paper trail** (NIST 600-1, ISO 42001 (S)): incident log, override log, per-release go/no-go record with model/prompt hashes, AI disclosure in greeting. Low effort, high defensibility.
10. **Fail-closed gate + trace ID + failure-class labels** (NIST MS-2.6-005 (S); MAST/τ-bench taxonomies (S); practitioner (P)). Verify the gate blocks on exception; label failures so the score explains itself.
11. **Prompt caching hygiene** (Anthropic docs (E)): stable prefix, state object after the breakpoint; a cost/latency win, not an intelligence win.
12. Shadow replay before prompt/model changes (P only) — useful, lowest evidence.

A reasonable 100-point split consistent with the above: 40 outcome (pass^3 on order state + facts), 25 policy/safety (gate rules, no manipulation, escalation), 20 conversation quality (isolated binary judges calibrated to owner labels), 15 language/culture (native-speaker blind rating). Report each with n and a 95% Wilson interval; version everything.

---

## Claims looked for and could not substantiate

- Any published **"intelligence score"** or quality score for a commercial customer-service agent (Intercom, Sierra, Salesforce, Decagon): none; all publish resolution/deflection rates with vendor denominators.
- An **independent audit** of any vendor's resolution-rate claim: none found.
- Official **Claude Opus 4 / GPT-5 model-card τ-bench numbers**: only third-party leaderboards reached.
- A **standards-body or regulator document** on canary/shadow rollouts or fail-closed defaults for LLM agents: none; practitioner blogs only.
- A **dedicated LLM benchmark for Swahili–English–Sheng code-switching** in conversation: none.
- Studies measuring **"emotion over-attribution"** or **"over-apology"** rates in LLM assistants by name: none; nearest are the apology-preference study (ACM 2026), tone-rebound bias (arXiv 2507.21083) and MISQ reactance.
- **Peer-reviewed validation of SPIN** (35,000-call study): none; proprietary. Challenger: proprietary, with peer-reviewed critiques.
- A **quantified consumer-harm figure** (money lost) from fake urgency: FTC/ICPEN measured prevalence, not harm; one $2.6M disgorgement case cited via law-firm summaries only.
- **Full text of ISO/IEC 42001** (paywalled; iso.org blocked fetch) and of the ACM apology paper (403); the MISQ paper itself (press release only).
- A **fixed sample-size rule** for human chatbot evaluation in any standard; interval arithmetic above is computed, not cited.
- Confirmation of a **Salesforce acquisition of Intercom Fin (2026)** seen in one low-quality source: unverified, ignored.
- Specific **ISO 42001 Annex A control IDs** for human oversight: consultancies disagree (A.4 vs A.9.4); not quoted.
