# Knowledge backlog — harvested gaps (deliberate edits, proven by battery re-runs)

- [ ] Explain-type risk types (e.g. "Risk Explain"): document exact p13 code(s),
      required params, and output shape in manuals/multirow.md + a menu line.
      Needs: one example URL + returned frame from the user.
- [ ] Desk limits/conventions: fill knowledge/desk.md (user).
- [ ] Menu completeness: which measures/cuts the desk ACTUALLY uses weekly
      (user pass over menu.md).
- [x] CONFIRMED LIVE (slice, 2026-07-07): risk explain is reachable as row
      grouping `CritPrdRiskExpain` (MRX's own spelling) on the multirow view —
      the designer+URL-builder found it from the menu's "explain-type" line
      alone, and the fetch succeeded. P3: document it properly in menu.md +
      manuals (breakdown-by-explain-category usage, output shape once seen).
- [ ] Window pinning: the three slice fetches derived "trailing month"
      independently (p28 = 06-05 / 06-06 / 06-08 — inconsistent starts). The
      blueprint should pin the exact window once; fetch requests carry it
      verbatim. (P3: designer prompt + fetch request phrasing.)
- [ ] MRX latency: a daily-history whole-node fetch hung >5 min (no pymrx
      timeout). Loop now enforces FETCH_TIMEOUT_S=180; tune from live data.
