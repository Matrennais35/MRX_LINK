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
- [x] CONFIRMED LIVE (slice #2): Risk Explain output shape — categories seen:
      New / Passive / Expired (rows via p1217=CritPrdRiskExpain,
      p1218=RowGrpRiskCmpnt), works with Current/Previous/Difference AND with
      p17 pair filters + arbitrary COB pairs (the targeted jump explain
      worked). P3: write this into menu.md + manuals properly.
- [ ] Designer latency: 105s at effort=high (the whole design phase). Lever:
      try designer=medium on the same question and compare blueprint quality
      (P3 experiment). Execute was 162s for 3 fetches + 6 python + ~8 calls.
- [ ] Fetch wall-time not measured (gate Steps record 0ms) — time the MRX
      call inside fetch_evidence for the P5 metrics.
- [ ] Pydantic "serializer warnings" on structured outputs — cosmetic
      langchain artifact; silence via warnings filter in the frontends.
- [ ] URL-builder prompt weight: every fetch carries ~78KB (manual + all
      tables) — measured via the bridge audit. Structural fix: the PHRASEBOOK
      (auto-recorded validated NL-request -> URL pairs as few-shots) and/or
      trimming tables to the sections the request needs.
- [x] Bridge-audit fixes (2026-07-07): concise frame labels (110-char slug
      observed), loop now told its seeded namespace at start, sim risk-type
      form returns one row like live MRX.
- [ ] PARAMETER-INVENTORY audit (bridge, 2026-07-07): we exploit ~15 of ~140
      multirow params. Now taught in menu.md: cross-tabs (p1029 second
      dimension), spot/vol-shift ladders, stress columns, product/deal/tenor/
      strike/trader/counterparty filters, server-side variation threshold
      (p1053), display currency (p1005, EUR default — reading.md corrected).
      TO VERIFY LIVE: (a) p1004=No ('Display as Tree' off) — may return FLAT
      rows and retire the Depth/leafify problem; (b) one cross-tab fetch
      (pair x tenor); (c) one spot-shift ladder; (d) variation threshold
      syntax. Then document output shapes in reading.md.
- [ ] Sim: add column-grouping support (cross-tabs, ladders) so these forms
      are testable offline.
