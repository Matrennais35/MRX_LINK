# Multirow Risk Snapshot — Full Parameter Spec (viewid=6168)

Every parameter accepted by the Multirow Risk Snapshot screen. In a URL each is written `p<ID>=<value>` (e.g. ID `1029` → `p1029=Total`), URL-encoded.

The screen is a **pivot table**: the X-axis is the **Columns** parameter (`p1029`) and the Y-axis is up to five nested **Row Level** parameters (`p1217`→`p1218`→`p1219`→`p1186`→`p1759`). Everything else is a filter or display option layered on top.

- **Validation `Mandatory`** — must be present in every Multirow URL.
- **Validation `Optional`** — include only when the user's request needs it.
- **Default** — value used when the parameter is omitted / the value to emit for a mandatory param when the user didn't override it.
- **Values from** — for coded parameters, the reference table that lists legal values.

| ID | Category | Label | Validation | Default | Values from | Notes |
|---|---|---|---|---|---|---|
| 1 | General | Node | Mandatory |  | free text |  |
| 1021 | General | Date Option | Mandatory |  |  | allowed: Current, Current, Previous, Difference |
| 1029 | General | Columns | Mandatory |  | columns_selection.md |  |
| 1217 | General | Row Level 1 | Mandatory |  | row_selection.md |  |
| 1218 | General | Row Level 2 | Optional |  | row_selection.md |  |
| 1219 | General | Row Level 3 | Optional |  | row_selection.md |  |
| 1186 | General | Row Level 4 | Optional |  | row_selection.md |  |
| 1759 | General | Row Level 5 | Optional |  | row_selection.md |  |
| 1017 | Portfolio Filters | GEaR Inclusion |  | Included |  |  |
| 1044 | Portfolio Filters | CVA VaR Perimeter | Optional |  |  |  |
| 1199 | Portfolio Filters | Basel 2.5 Capital | Optional |  |  |  |
| 1175 | Portfolio Filters | Risk Quality | Optional | Usable |  |  |
| 1000 | Portfolio Filters | Portfolio Category | Optional |  |  |  |
| 1344 | Portfolio Filters | Legal Entity | Optional |  |  |  |
| 1142 | Portfolio Filters | Internal Risk Transfer Positions | Optional |  |  | Internal Risk Transfer Positions |
| 1669 | Portfolio Filters | Signing Entity | Optional |  |  |  |
| 1129 | Tracking | Included Nodes | Optional |  |  |  |
| 1130 | Tracking | Excluded Nodes | Optional |  |  |  |
| 1131 | Tracking | Node Tracking Type | Optional |  |  |  |
| 1132 | Tracking | Node Tracking Level | Optional |  |  |  |
| 1133 | Tracking | Event Triggering | Optional |  |  |  |
| 1134 | Tracking | Scheduled Time | Optional |  |  |  |
| 1135 | Tracking | Retriggerable System Events | Optional |  |  |  |
| 1155 | Tracking | Non-Retriggerable System Events | Optional |  |  |  |
| 27 | Date Option | Current Date | Mandatory |  |  |  |
| 28 | Date Option | Previous Date | Mandatory | T-1 |  |  |
| 13 | Filters | Risk Type |  |  | risk_type_selection.md | filterID 2001 |
| 1042 | Filters | Risk Component |  |  | free text |  |
| 1670 | Filters | Add/Remove Result Columns |  |  |  |  |
| 1176 | Filters | Risk Site | Optional |  |  |  |
| 1001 | Filters | Portfolio Code | Optional |  | free text |  |
| 1036 | Filters | Currency | Optional |  | free text |  |
| 17 | Filters | Underlying | Optional |  | free text |  |
| 1183 | Filters | Undg Ccy | Optional |  | free text |  |
| 1287 | Filters | Product Family | Optional |  |  |  |
| 1049 | Filters | Product Type | Optional |  |  | filterID 2002 |
| 43 | Filters | Product | Optional |  |  |  |
| 1167 | Filters | Contract Type | Optional |  |  |  |
| 1168 | Filters | Generic Name | Optional |  |  |  |
| 1047 | Filters | Deal/Security | Optional |  | free text |  |
| 1040 | Filters | Tnr (Sw) | Optional |  | free text |  |
| 1041 | Filters | Tnr (Opt) | Optional |  | free text |  |
| 1050 | Filters | Strategy | Optional |  | free text |  |
| 2014 | Filters | HF Strategy 1 | Optional |  |  |  |
| 2016 | Filters | Tiering | Optional |  |  |  |
| 1054 | Filters | File | Optional |  | free text |  |
| 1059 | Filters | Gtr Code | Optional |  | free text |  |
| 1074 | Filters | Issuer Code | Optional |  | free text |  |
| 1061 | Filters | Spot Shift | Optional |  |  |  |
| 1062 | Filters | Vol Shift | Optional |  |  |  |
| 1120 | Filters | Strike | Optional |  |  |  |
| 1208 | Filters | Security Type | Optional |  |  |  |
| 1209 | Filters | Undg (deal) | Optional |  | free text |  |
| 1083 | Filters | Currency (deal) | Optional |  | free text |  |
| 1412 | Filters | Currency2 (deal) | Optional |  | free text |  |
| 1286 | Filters | Issuer (Deal) | Optional |  |  |  |
| 1308 | Filters | Guarantor (deal) | Optional |  |  |  |
| 1350 | Filters | Guarantor Real Country (deal) | Optional |  |  |  |
| 1241 | Filters | Guarantor Macro Sector | Optional |  |  |  |
| 1226 | Filters | Repo Bond Country | Optional |  |  |  |
| 1332 | Filters | Front Loading Category | Optional |  |  |  |
| 1178 | Filters | Linked Underlying | Optional |  |  |  |
| 1184 | Filters | Trade Date | Optional |  |  |  |
| 1188 | Filters | Forward Start Date | Optional |  |  |  |
| 1043 | Filters | MrxTest (Sns Nam) | Optional |  |  |  |
| 1110 | Filters | Maturity (deal) | Optional |  |  |  |
| 1073 | Filters | Limit Levels | Optional | Activity,CMRC,Metier,Local-RiskIM,Local-V&RC |  | allowed: Metier,Activity,Local-RiskIM,CMRC,Local-V&RC |
| 1292 | Filters | Instrument SubType | Optional |  |  |  |
| 1293 | Filters | Instrument Class | Optional |  |  |  |
| 1154 | Filters | Currency Country | Optional |  |  |  |
| 2380 | Filters | Non-Deliverable Flag | Optional |  |  |  |
| 3027 | Filters | Gtr Legal Entity | Optional |  |  |  |
| 3028 | Filters | Gtr RMPM Code | Optional |  |  |  |
| 3029 | Filters | Protection End Date | Optional |  |  |  |
| 2103 | Filters | Trader | Optional |  |  |  |
| 2505 | Filters | Trader Details | Optional |  |  |  |
| 1675 | Counterparty Filters | CRDS Code | Optional |  |  |  |
| 1693 | Counterparty Filters | Name | Optional |  |  |  |
| 1685 | Counterparty Filters | RMPM Code | Optional |  |  |  |
| 1684 | Counterparty Filters | Classification | Optional |  |  |  |
| 1687 | Counterparty Filters | Type | Optional |  |  |  |
| 1683 | Counterparty Filters | Country of Incorporation | Optional |  |  |  |
| 1686 | Counterparty Filters | Industry | Optional |  |  |  |
| 1701 | Counterparty Filters | Counterparty rating | Optional |  |  |  |
| 1780 | Counterparty Filters | Sub Industry | Optional |  |  |  |
| 3007 | Counterparty Filters | Cpty NACE Name | Optional |  |  |  |
| 1676 | Group Counterparty Filters | CRDS Code | Optional |  | free text |  |
| 1707 | Group Counterparty Filters | Name | Optional |  | free text |  |
| 1708 | Group Counterparty Filters | RMPM Code | Optional |  |  |  |
| 1806 | Group Counterparty Filters | Classification | Optional |  |  |  |
| 1706 | Group Counterparty Filters | Country of Incorporation | Optional |  |  |  |
| 1781 | Group Counterparty Filters | Sub Industry | Optional |  |  |  |
| 3003 | Orig Counterparty Filters | Type | Optional |  |  |  |
| 3006 | Orig Counterparty Filters | Country of Incorporation | Optional |  |  |  |
| 3004 | Orig Counterparty Filters | Country of Business | Optional |  |  |  |
| 3005 | Orig Counterparty Filters | Cpty Customer Flag | Optional |  |  |  |
| 1673 | Booking Counterparty Filters | CRDS Code | Optional |  | free text |  |
| 1725 | Booking Counterparty Filters | Name | Optional |  | free text |  |
| 1751 | Booking Counterparty Filters | RMPM Code | Optional |  |  |  |
| 1750 | Booking Counterparty Filters | Country of Incorporation | Optional |  |  |  |
| 1807 | Booking Counterparty Filters | Classification | Optional |  |  |  |
| 1711 | Legal Mitigant Filters | MA | Optional |  |  |  |
| 1710 | Legal Mitigant Filters | CSA | Optional |  |  |  |
| 1179 | Legal Mitigant Filters | CSA Discount Curve | Optional |  |  |  |
| 1207 | Legal Mitigant Filters | MA Type | Optional |  |  |  |
| 1261 | Legal Mitigant Filters | Front Office CSA | Optional |  |  |  |
| 1269 | Legal Mitigant Filters | Front Office Collateral Family | Optional |  |  |  |
| 1270 | Legal Mitigant Filters | Front Office Collateral Sub Family | Optional |  |  |  |
| 1271 | Legal Mitigant Filters | Front Office Collateral Discount Curve | Optional |  |  |  |
| 1127 | Legal Mitigant Filters | Legal Mitigant Type | Optional |  |  |  |
| 1331 | Filters | Intra Day Time | Optional |  |  |  |
| 1088 | Counterparty (old) Filters | Counterparty Code | Optional |  |  |  |
| 2021 | Counterparty (old) Filters | Counterparty Type | Optional |  |  |  |
| 1161 | Counterparty (old) Filters | Cpty Country | Optional |  |  |  |
| 1162 | Counterparty (old) Filters | CRDS Cpty BNPA Classif | Optional |  |  |  |
| 1164 | Counterparty (old) Filters | Cpty RMPM Code | Optional |  |  |  |
| 1165 | Counterparty (old) Filters | CRDS Cpty Type | Optional |  |  |  |
| 1079 | Counterparty (old) Filters | Counterparty Definition | Mandatory | GRP |  |  |
| 1005 | Display | Display Currency |  | EUR |  |  |
| 1004 | Display | Display as Tree |  | Yes |  |  |
| 1016 | Display | Tenor Display |  | Full Tenors |  |  |
| 1201 | Display | Maturity Bucketing |  | Fixed Tenors |  |  |
| 9876 | Display | Min/Max Display |  | No |  |  |
| 1031 | Display | Total Column |  | None |  |  |
| 1003 | Display | Total Row |  | None |  |  |
| 1053 | Display | Variation Threshold (Abs.) | Optional |  |  |  |
| 1011 | Display | Variation Criteria |  | And |  |  |
| 1010 | Display | Variation Threshold (Rel.) | Optional |  |  |  |
| 1006 | Display | Threshold | Optional |  |  |  |
| 1169 | Display | Result Display | Optional | Standard |  |  |
| 2475 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2476 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2490 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1348 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1870 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 99405 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1909 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1910 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 11017 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1343 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2435 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1063 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 10003 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1380 | Advanced (undocumented) | — | Optional |  |  | Product SubType FOCUS; valid but not in the human spec — use only if explicitly requested |
| 2438 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2509 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2373 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2374 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2503 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1364 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1349 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1351 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1353 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1355 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1359 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3013 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3014 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3015 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3016 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3017 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3101 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3502 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1729 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3503 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1805 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1699 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1808 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9934 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2220 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9935 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1674 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1402 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2350 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2351 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1228 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1688 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1698 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1697 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9933 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1983 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1370 | Advanced (undocumented) | — |  |  |  | valid but not in the human spec — use only if explicitly requested |
| 2370 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2223 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1932 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1963 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1400 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1200 | Advanced (undocumented) | — | Optional | No |  | valid but not in the human spec — use only if explicitly requested |
| 1160 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1846 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1847 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1867 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1868 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1358 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2241 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9198 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2281 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2070 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 10000 | Advanced (undocumented) | — | Optional |  |  | hidden; valid but not in the human spec — use only if explicitly requested |
| 10018 | Advanced (undocumented) | — | Optional |  |  | hidden; valid but not in the human spec — use only if explicitly requested |
| 10021 | Advanced (undocumented) | — | Optional |  |  | hidden; valid but not in the human spec — use only if explicitly requested |
| 10025 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1895 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1339 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1341 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 10026 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2493 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1198 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 12870 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 4806 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3894 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2262 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 22621 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3108 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1243 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2030 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9975 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2429 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2452 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 10001 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 10002 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1289 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2433 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2511 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2508 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1978 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1583 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 4994 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1982 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1856 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 6661 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 2542 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9958 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 9957 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 99404 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 6662 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 6663 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 7997 | Advanced (undocumented) | — | Optional |  |  | Model Component (used); valid but not in the human spec — use only if explicitly requested |
| 7996 | Advanced (undocumented) | — | Optional |  |  | Model Instrument (used); valid but not in the human spec — use only if explicitly requested |
| 1991 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 7353 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 7354 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 7355 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 1144 | Advanced (undocumented) | — | Optional |  |  | Risk Perspective; valid but not in the human spec — use only if explicitly requested |
| 3313 | Advanced (undocumented) | — | Optional |  |  | ADV 3M Tiering; valid but not in the human spec — use only if explicitly requested |
| 1387 | Advanced (undocumented) | — | Optional |  |  | Clean Price; valid but not in the human spec — use only if explicitly requested |
| 2506 | Advanced (undocumented) | — | Optional |  |  | Outstanding Amount USD; valid but not in the human spec — use only if explicitly requested |
| 2513 | Advanced (undocumented) | — | Optional |  |  | Coupon; valid but not in the human spec — use only if explicitly requested |
| 1779 | Advanced (undocumented) | — | Optional |  |  | Attachment Point (Deal); valid but not in the human spec — use only if explicitly requested |
| 1767 | Advanced (undocumented) | — | Optional |  |  | Detachment Point (Deal); valid but not in the human spec — use only if explicitly requested |
| 1493 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |
| 3317 | Advanced (undocumented) | — | Optional |  |  | BICS Sector; valid but not in the human spec — use only if explicitly requested |
| 7000 | Advanced (undocumented) | — | Optional |  |  | valid but not in the human spec — use only if explicitly requested |

> The screen displays risks according to the selection of the X-axis (Columns, `p1029`) and the Y-axis (Rows, `p1217`…). For example Columns could be Product and Rows could be Tenor.
