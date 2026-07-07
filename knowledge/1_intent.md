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

## When to ask back instead of guessing
Ask ONE clarifying question (and stop) only when the ambiguity changes what
would be fetched or concluded AND no sensible default exists — e.g. the
question names no measure at all on a node carrying many ("Analyse GFXOPEMK"
still proceeds: level+change+drivers on the node's main measures is the
sensible default). Never ask when a stated default resolves it.
