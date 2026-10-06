# UX & Accessibility Pass — Language Guide

This documents the language, conversation, and accessibility changes made in
this pass. The goal throughout: someone with no resume, no formal education,
and no familiarity with career/HR terminology should be able to use every
part of this platform comfortably — a homemaker, farmer, tailor, delivery
partner, driver, shop owner, small business owner, caregiver, volunteer,
student, office worker, or freelancer.

**Nothing about the AI or the underlying analysis was simplified or
removed** — every score, every engine, every data point still exists and is
still computed exactly as before. Only how it's *shown and explained* changed.

## 1. Language Mapping (Before → After)

| Before | After | Where |
|---|---|---|
| Career Readiness (score) | How Ready You Are for Your Next Opportunity | Copilot, Career Hub |
| ATS Score | Resume Quality | Career Hub, Copilot |
| Skill Gap | Skills You Can Learn Next | Career Hub, Copilot |
| Confidence Score / raw % | "We're quite sure" / "We're fairly sure" / "Still learning about this" | Dashboard "why this skill" panel, Career Hub explanations, Copilot |
| Opportunity Engine | Jobs That Match Your Strengths | Dashboard |
| Recruiter Summary | Your Story, Summed Up | Career Hub |
| Technical / Leadership / Communication / Consistency / Growth Score | Skills & Know-How / Leading Others / Explaining Things Clearly / Staying Consistent / Growing Over Time | Career Hub, Dashboard radar |
| Leadership Index | Leadership Shown | Dashboard |
| Employability Score | Job Readiness | Dashboard |
| Strong / Developing / Needs Work (tier) | Great / Growing / Just Starting | Career Hub |
| Skills You Have / Partial Overlap / Skills to Develop | Things You Already Do Well / You're Partway There / Skills You Can Learn Next | Career Hub |
| Missing ATS Keywords | Words Worth Adding to Your Resume | Career Hub |
| Contributing Factors / Matched Evidence / How to Improve | Why We Think This / Where We Saw It In Your Story / How to Strengthen This | Career Hub explanation panel |
| Raw similarity % (e.g. "87%") | "Strong match" / "Good match" / "Some overlap" | Career Hub skill lists |
| "core" / "supporting" skill tier | "Especially useful" / "Good to have" | Career Hub |
| "No missing skills — excellent!" | "You're already covering everything important — wonderful!" | Career Hub |

## 2. Question Flow (Task 2)

The Dashboard's activity-logging questions were **kept structurally the
same** (same 8 concrete, example-driven prompts) rather than replaced with
open-ended "tell us about your day" boxes. This was a deliberate decision:
concrete, guided prompts with a worked example ("e.g., Rs 5,000 for
groceries") are *more* accessible for someone with lower digital literacy or
less confidence in writing than a blank narrative box — they show exactly
what kind of answer is expected. What changed is the tone:

| Before | After |
|---|---|
| "What specific activity did you lead today?" | "What's something you took charge of recently?" |
| "How many people did you coordinate?" | "Were other people involved or counting on you?" |
| "What was the total budget you handled?" | "Did you handle any money for this? Roughly how much?" |
| "Who was the primary audience or beneficiary?" | "Who was this for?" |
| "How did you handle any conflicts or sudden changes?" | "Did anything go wrong or change suddenly? How did you handle it?" |
| "What was the absolute hardest part of this task?" | "What was the hardest part?" |

The card's intro line changed from *"What did you manage today? Explain your
unpaid labor."* to *"There's no wrong answer here — just tell us about
something you handled recently, in your own words."*

## 3. AI Copilot Personality (Task 5)

The Copilot's system prompt was rewritten from an "encouraging career
mentor" persona to an explicit, detailed set of plain-language rules — see
`services/ai_copilot.py`'s `_SYSTEM_INSTRUCTIONS`. Key additions:
- Explicit list of banned jargon terms and their plain replacements.
- An explicit rule to never phrase anything as a deficiency ("you lack
  leadership" → "we haven't found many examples of this yet — tell us more").
- A reminder of who's actually using this platform, so the model doesn't
  default to resume-industry assumptions.

The **local fallback responder** (what most people actually experience,
since Gemini is often not configured) was rewritten in full — every
canned response now uses the same plain-language, encouraging tone. This is
tested: see `tests/test_copilot_language.py`, which specifically checks
that common ML/HR jargon terms never appear in fallback answers, and that
low scores are never phrased as "lack" or "poor" or "bad".

## 4. Human-Centered Explanations (Task 4, 11)

- **Fixed a real bug**: the Dashboard's "why this skill?" panel was
  literally showing a developer-facing message — *"Local NLP engine error.
  Please run: `pip install sentence-transformers`"* — directly to end
  users. This is now a warm, honest message with no code or technical
  instructions.
- Raw confidence percentages (e.g. "73% confidence") were replaced
  throughout with plain-language equivalents ("We're quite sure about this
  one" / "We're fairly confident" / "We think this might apply").
- The Career Hub's per-axis explanation accordion now shows "Why We Think
  This" / "Where We Saw It In Your Story" / "How to Strengthen This"
  instead of "Contributing Factors" / "Matched Evidence" / "How to Improve".

## 5. Career Journey Visual (Task 7)

A new section was added to the top of the Career Hub's results (see
`career.html`'s `#journeyTrack`, styled via `styles.css`'s "Career Journey
visual" block): a five-step horizontal path —

**What You're Already Great At → Hidden Skills We Found → Jobs You Could
Explore Today → Skills You Can Learn Next → Where This Could Take You**

Built entirely from data already being fetched for the rest of the page
(recruiter strengths, matched skills, opportunity recommendations, missing
skills) — no new analysis, just a friendlier front door to the same
information before the more detailed panels below it.

## 6. Positive Feedback Framing (Task 10)

Every place that could read as a judgment was reframed as an invitation to
share more, per the brief's own example:

> Instead of "You have poor leadership," use "We couldn't identify enough
> examples of leadership yet. If you've organised people or coordinated
> activities, tell us more so we can recognise those strengths."

Applied to: the tier labels (Strong/Developing/Needs Work → Great/Growing/
Just Starting), empty states across the Career Hub's skill panels, and the
Copilot's system prompt and local fallback.

## 7. Accessibility (Task 8)

Scoped to what's safe without "completely redesigning the visual identity"
(per the brief's own constraint): simpler sentences and shorter labels
throughout, warmer empty/loading/error states, and the Career Journey visual
as a lower-cognitive-load entry point before the denser score panels. No
layout, color system, or component redesign was done — this pass is
language-and-copy-focused, not a visual overhaul.

## 8. Multilingual Experience (Task 9) — Honest Limitation

This platform supports English plus six other languages via Flask-Babel.
**I did not attempt to rewrite or verify the actual translated strings in
Hindi, Kannada, Tamil, Telugu, Marathi, or Bengali** — I'm not a native or
fluent speaker of any of them, and claiming to have made those translations
"feel natural" without genuinely being able to judge that would be
dishonest. What I *can* do, and did: simplify the **English source strings**
that get wrapped in `{{ _('...') }}` for translation (see the language
mapping table above) — simpler English source text gives whoever
translates it a better starting point. **Recommended next step**: a review
pass by a native speaker of each supported language, specifically checking
for direct/awkward technical translations per the brief's own concern.

## 9. What Was NOT Changed (Scope Decisions)

- **login.html / register.html**: reviewed, left mostly as-is — these pages
  were already simple ("Welcome back", "Create account") with little
  jargon to remove. Effort was concentrated on the Dashboard, Career Hub,
  and Copilot, which had the actual technical terminology.
- **PDF exports** (`services/pdf_design.py`, the two PDF generator routes):
  not touched in this pass. They already went through a separate, careful
  redesign effort with their own extensive test coverage; re-touching that
  copy risked real regressions for a lower-traffic surface (a downloaded
  document, not the live interactive experience most users spend time in).
  Worth a dedicated follow-up pass using the same language mapping above.
- **Underlying data model / stored values** (e.g. `leadership_category`
  column values like "Strategic Planning", "Empathy & Crisis Management"):
  left untouched. These are real stored data and scoring-engine lookup
  keys, not just display text — renaming them would risk breaking scoring
  logic for no user-facing benefit beyond what a display-only mapping layer
  (which *was* added, in `script.js`) already achieves safely.

## 10. Second Pass — Messages, Tooltips, and Table Labels

A follow-up review (prompted by a repeat of this same brief) went deeper
into surfaces the first pass didn't fully cover:

- **All 13 flash messages** in `app.py` (login/register/logout/target-role
  errors and confirmations) rewritten warmly — e.g. "Invalid username or
  password." → "We couldn't find an account with that username and
  password. Please double-check and try again."; "Security token expired.
  Please try again." → "That took a little too long — please refresh the
  page and try again."
- **11 `jsonify` error/success messages** rewritten the same way (activity
  submission, resume upload, target role, PDF generation).
- **A real jargon leak on the History page**: a tooltip literally read
  *"Embedding-based semantic match confidence — see Phase 3 NLP engine"* —
  internal engineering documentation shown as a user-facing tooltip. Now
  reads "How sure we are that this is the right skill match," with the
  badge itself showing "We're quite sure" / "We're fairly sure" / "Still
  learning about this" instead of a raw percentage.
- **Cryptic abbreviations on the History page table** ("Str 78", "Fin 65",
  "Crs 40", "Tm 82", "Emo 55") replaced with full words ("Plan 78", "Money
  65", "Problems 40", "Team 82", "People 55"), each with a plain-language
  tooltip. Column headers "Activity"/"Professional Title"/"Radar
  Skills"/"Leadership"/"Employability" renamed to "What You Did"/"Skill We
  Found"/"Key Strengths"/"Leadership Shown"/"Job Readiness".
- Mic-button tooltips ("Click to dictate") simplified to "Click to speak
  instead of typing."

All changes re-verified: full HTML re-validation, full 96-test suite
re-run, full live-route regression re-run — all passing.


- `tests/test_copilot_language.py` (new): locks in that the Copilot's local
  fallback never uses raw jargon terms and never phrases things as a
  deficiency.
- Full existing test suite (96 tests) re-run and passing after every change
  in this pass.
- Every HTML file re-validated for well-formedness; every inline/external
  JS file re-checked with `node --check` after edits.
- Full live-route regression check (Dashboard, Career Hub, both PDFs,
  History, Copilot, health check, API docs) re-run and passing.

## 11. Third Pass — Explaining WHY, and the Copilot Widget's Own Text

A third review targeted Task 5 specifically (explaining *why* something was
recommended, not just what) plus the floating Copilot widget's own UI text,
which hadn't been reviewed in either prior pass.

**Recommendations now explain why** (`career.html`'s Opportunities section):
- A new intro line above the recommendation cards: *"Chosen because you've
  already shown skills like [X] and [Y] — these build on that, and move
  you closer to [target role]."* — built from the same matched-skills data
  already on the page, no new analysis.
- Each category (Projects, Hackathons, Certifications, Open Source) now
  has its own one-line "Why:" explanation on its first card, e.g. *"Why:
  hands-on practice that shows employers what you can do for this role."*
- The backend's existing "priority note" (`services/opportunity_recommender.py`)
  was reworded from "it's your most critical missing core skill for this
  role" to "this is one of the most useful skills to pick up for this
  role" — a pure string change, no logic touched.

**The Copilot widget's own text** (`copilot_widget.js` — not reviewed in
prior passes):
- Input placeholder: *"Ask about your career readiness, skills,
  roadmap..."* → *"Ask me anything — how ready you are, what to learn
  next, what to try..."*
- Suggested question chips reworded to match the language mapping (e.g.
  "Explain my Career Readiness score" → "How ready am I for my next
  opportunity?").
- The answer "insight" panel's labels — Evidence / Confidence / Next step /
  Impact / Effort — renamed to Based on / How sure we are / Try this next /
  Why it helps / Time needed.
- The widget's own header, previously "AI Career Copilot," renamed to
  "Your Career Guide" — matching the brief's explicit goal that this should
  feel like a friendly guide, not a technical AI tool. (Internal file/route
  names like `ai_copilot.py` and `/copilot/ask` are unchanged — those
  aren't user-facing.)

Re-verified: full test suite (96 passing), HTML/JS syntax checks, and full
live-route regression, all after these changes.

