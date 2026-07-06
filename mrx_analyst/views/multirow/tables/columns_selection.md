# Column Group Values (p1029)

Values usable for the **column grouping** on the X-axis, passed as **`p1029`**.
`p1029` is mandatory and defaults to `Total`. Two special notes:
- Use **`History dates`** to put a date range across the columns (see the manual's "Dates in columns" variant).
- The MRX URL for `p1029` takes the **Display Name** (e.g. `p1029=Product`, `p1029=Tnr+(Opt)`), URL-encoded — not the internal `ColGrp…` code. The Code column is shown for reference/traceability.

| Display Name (use in p1029) | Internal Code |
|---|---|
| IR Spot and Vol Risks | ColGrpIrSpotVolRisks |
| IR Spot Risks | ColGrpIrSpotRisks |
| IR Vol Risks | ColGrpIrVolRisks |
| FX Exposure | ColGrpFxExposure |
| Official Stress Scenarios | ColGrpTvlMrcStressScenarios |
| Product | ColGrpPrdDsc |
| Portfolio | ColGrpPtfCod |
| Currency | ColGrpCurrency |
| Currency Pair | ColGrpCcyPair |
| Underlying | ColGrpUnderlying |
| Underlying Type | ColGrpUndgType |
| Underlying Currency | CritUndgCcy |
| Maturity (deal) | ColGrpMaturity |
| Tnr (Sw) | ColGrpTnr1 |
| Tnr (Opt) | ColGrpTnr2 |
| Total | ColGrpTotal |
| Risk Component | ColGrpRiskCmpnt |
| Risk Site | CritRskSit |
| Listed Market Code | CritPrdIsListed |
| Clearer | CritPrdClearer |
| Clearer (end) | CritPrdClearerEnd |
| Risk Type | ColGrpRiskType |
| PnL Type | CritSnsTypGroup |
| PnL Type (With Diff) | ColGrpSnsTypGroupDiff |
| PnL Category | CritSnsTypCategory |
| Credit Risks Overview | ColGrpCrdOverview |
| Issuer Risk/SP01 per Tenor | ColGrpIssuerRiskSp01 |
| Spot Shift | ColGrpShf1Float |
| Vol Shift | ColGrpShf2Float |
| Vol Shift (Inf) | ColGrpShf3Float |
| Legal Mitigant Type | CritLegalMitigantType |
| CSA Discount Curve | CritLegalMitigantDscCrv |
| Deal/Security | ColGrpPrdInlNo |
| Product Type | ColGrpPrdTyp |
| Maturity (Curve) | ColGrpMaturityCurve |
| Maturity (Curve) MDDR | CritPosMatDtMDDR |
| Guarantor | CritGtr |
| Gtr Sector Name | CritGtrSectorName |
| Guarantor Country | ColGrpGtrCountry |
| Underlying Rating | ColGrpGtrRtg |
| Rating | ColGrpGtrRtg |
| Seniority | ColGrpGtrSenr |
| IR Stress Test | ColGrpStressIr |
| CR Stress Test | ColGrpStressCredit |
| CR CCAR Stress Test | ColGrpStressCreditCCAR |
| CO CLEAR Stress Test | ColGrpStressCoFullRevalClear |
| DEC - IR Listed Derivatives | ColGrpDecIrListedDerivatesFull |
| EQ CLEAR Stress Test | ColGrpStressEqClearStress |
| EQ CLEAR Stress Test New | ColGrpStressEqClearStressNew |
| FXLD Stress Conc. | ColGrpFxldStressConcentration |
| FXLD Stress Conc. Systemic | ColGrpFxldStressFullSystemic |
| FX PB Stress Test Conc | ColGrpStressFxPbConcAll |
| FX PB Stress Test | ColGrpStressFxPbAll |
| FX Stress Test - FX Exposure | ColGrpStressFXComb |
| FX Stress Test - FX Spot Grid | ColGrpStressFx |
| FX Stress Test - Stress Testing | ColGrpStressFxStress |
| EQD Stress Test - Snipers | ColGrpStressEQDSnipersWithCredit |
| EQD Stress Test - Snipers exc. Credit | ColGrpStressEQDSnipers |
| EQD CCAR Stress Test | ColGrpStressEQD_CCAR |
| CO Stress Test | ColGrpStressCoFullReval |
| CO CCAR Stress Test | ColGrpStressCoFullRevalCCAR |
| Full Stress Test | ColGrpStressFullStressGreeks |
| CCAR CDL Stress Test | ColGrpCcarCdlDealTotal |
| Group Stress Test (ReST) | ColGrpRestDealTotal |
| Group Stress Test (BEST) | ColGrpBestDealTotal |
| SVAA SFT | ColGrpLegPvSft |
| SVAA PB | ColGrpLegPvPbTotal |
| SVAA SFT Basel IV | ColGrpLegPvSftB4 |
| SVAA PB Basel IV | ColGrpLegPvPbTotalB4 |
| Haircut Floor SFT | ColGrpLegPvSftHcFloor |
| MRX File | ColGrpFile |
| Basket (Deal) | ColGrpUndgDeal |
| Spread Band | ColGrpSprd |
| Spread Band (Limits) | CritUndgSpdLvlBcktLimits |
| Strategy | ColGrpStrategy |
| HF Strategy | ColGrpHFStrategy |
| Credit Spread Delta : SP01/PSP1% | ColGrpCrdSp01Psp1 |
| Cpty - Type | CritCptyClcCrdsTyp |
| Cpty - Classification | CritCptyClcType |
| Cpty - Name \| CRDS | CritCptyCLC |
| Grp Cpty - Name \| CRDS | CritCptyGRP |
| GGC Credit Risks Overview | ColGrpCrdSp01BondBasis |
| ODC | ColGrpODC |
| Strike | ColGrpPosStrike |
| Risk Type by Long/Short | ColGrpLongShortRiskType |
| Risk Type by Long/Short (Strategy) | ColGrpLongShortStgyRiskType |
| Risk Type by Long/Short (Country) | ColGrpLongShortCtyRiskType |
| Long/Short (undg (deal)) | ColGrpLongShortUndgRiskType |
| Issuer Rating | ColGrpIssrRtg |
| Node | ColGrpNodeCode |
| Focus Desk | ColGrpFocusDesk |
| Focus Alias | CritUndgFocusAlias |
| Guarantor Rating | ColGrpGtrPtyRtg |
| Guarantor Real Country | ColGrpGtrRealCountry |
| Guarantor Region | CritGtrRegion |
| Guarantor ICB Sector | CritGtrIcbSector |
| MRX Seniority | CritUndgMrxSen |
| Credit Spread Delta : SP01/SP1% | ColGrpCrdSp01Sp1 |
| FO CSA Family | CritFoCsaFam |
| FO CSA Sub Family | CritFoCsaSubFam |
| FO CSA Discount Curve | CritFoCsaDiscCrv |
| Counterparty | CritCpty |
| Counterparty Country | CritCptyCty |
| Counterparty Group | CritCptyGrpName |
| Buy/Sell(deal) | CritPrdBuySellFlg |
| Underlying Rating (Cumulated) | ColGrpUndgCumulativeRtg |
| Underlying Rating (Cumulated with Pos) | ColGrpPrdUndgCumulativeRtgWithPos |
| Underlying (deal) Rating Cumulated | ColGrpPrdUndgCumulativeRtg |
| Results | ColGrpResults |
| TBA Program | CritPrdUndgMBSAgcyTBA |
| CDS Spread 5Y | CritPrdUndgCDS5Y |
| Max Maturity (deal) | ColGrpMaxMaturity |
| Detach Point (deal) | CritPrdDetPnt |
| Bucket Detach Point (deal) | CritBucketDetachPoint |
| Attach Point (deal) | CritPrdAttPnt |
| Trade Date | CritPrdCmtDt |
| IntraDay Snapshot | CritIntraDaySnapshot |
| History dates | ColGrpHistory |
| Underlying (deal) | CritPrdUndg |
| CSA Name | CritCsaNam |
| CSA Lookup Date | CritCsaLkpDt |
| Tenor (Sw) SFT Gapping | ColGrpTnrSwGapping |
| Signing Entity | CritSgnEnt |
| Instrument Class | CritPrdUndgClassType |
| Instrument SubType | CritPrdUndgSubTyp |
| Security Type | CritPrdSecTyp |
| Node and Children | ColGrpSubNodes |
| Scenario | CritScenario |
| PnL Feed Type | CritFilePnLFeedType |
