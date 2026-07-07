---
name: intent
when_to_use: Reading any user question — deriving the target before designing the answer.
examples:
  - "Analyse the variation of FX Vega on GFXOPEMK over the last month."
  - "What is the total EQ Delta Cash for US_SPX?"
---

# Reading the question

The user is a market-risk analyst. Derive the TARGET — the decision or insight
behind the words, not a restatement. "Analyse the variation" is not answered
by a number; it is answered by explaining what moved, when, why (as far as the
data allows), and whether it matters.

## Defaults (apply silently, state them in the answer's data context)
- No date given, or "today"/"latest": the latest available COB (T-1 — MRX has
  data only up to the previous business day; weekends/holidays roll back).
- "Last month" / "this week": a trailing window ending at the latest COB.
- No scope qualifier: the node/perimeter named in the question, whole.
- Size of the answer follows the size of the question: a lookup gets two
  sentences and one number; "analyse X" earns a sectioned note.

## The clarification round-trip
When the PREVIOUS turn in the conversation was OUR clarifying question, the
user's new message is the ANSWER to it: design for the ORIGINAL question with
the ambiguity resolved — never re-ask, never treat the reply as a standalone
question.

## Assume-then-run (the default), ask back (the exception)

Under-specified but reasonably interpretable -> DO NOT ask back. Make
explicit, reasonable assumptions (window, COB, measure, scope — using the
defaults above), record them in the blueprint's `assumptions`, design and
EXECUTE the full answer; the note's summary states the assumptions and
invites refinement. An answer with stated assumptions beats a question back.

Set `clarification` ONLY when BOTH hold: the ambiguity would materially
change the fetch or the conclusion, AND no sensible default or conversation
context resolves it (e.g. no node named anywhere). Then ask ONE precise
question.
