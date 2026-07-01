# Risk Type Codes (p13)

The risk measure to display, passed as **`p13`** in the Multirow URL.
Use ONLY codes from this table — never invent a code. For generic greek names ("delta", "vega", "gamma"), disambiguate with the node's asset class (see the manual's Risk Type Disambiguation section).

| Display Name | Code (p13) |
|---|---|
| EQ Delta Cash | EQDELTACASH |
| EQ Gamma Cash | EQGAMMACASH |
| EQ Cross Gamma | EQCROSSGAMMA |
| EQ Wizoo MRX ATM (EQ Vega) | EQWIZOOMRXATM |
| EQ Cross Wizoo MRX ATM | EQCROSSWIZOOMRX |
| EQ Vega Long-Term | V_GR_EQVEGA_LT |
| EQ Vega Short-Term | V_GR_EQVEGA_ST |
| EQ Dividend Pillar | EQDIVPILLAR |
| EQ Rho Prop Dividends | EQRHOPROPDIV |
| EQ PV Diff | EQPVDIFF |
| EQ Delta Desloping | V_EQVEGADESLOPE |
| EQ Parallel Correlation | EQCORRELNEW |
| EQ Smile Pillar | EQSMILEPILLAR |
| EQ Curve Pillar | EQCURVEPILLAR |
| EQ Repo Pillar Projection | EQREPOBUCKETPJC |
| EQ M8M7 Delta Cash | EQDELTACASHM8M7 |
| IR Delta (PV01/DV01) | IRDELTA |
| IR Vega | IRVEGA |
| IR Cash Vega | CASHVEGA |
| IR Gamma +10 | IRGAMMAUP |
| IR Gamma -10 | IRGAMMADN |
| IR Cross Gamma (CRM) | IRXGAMMACRM |
| IR Rho | IRRHO |
| IR Alpha | IRALPHA |
| IR Beta | IRBETA |
| IR Vanna Average | V_IRVANNAAVG |
| IR Volga Average | V_IRVOLGAAVG |
| IR Rho Fwd (Ext.) | V_GR_IRRHOFWD |
| IR Alpha Fwd (Ext.) | V_GR_IRALPHAFWD |
| IR Vega Fwd (Ext.) | V_GR_IRVEGFWD |
| IR Basis Spread (Ext.) | V_GR_IRSPD_NCMT |
| IR CMT Spread (Ext.) | V_GR_IRSPD_CMT |
| FX Vega (Soho) | FXVEGASOHO |
| FX Gamma Multi | FXGAMMAMLT |
| FX Grid (Soho) | FXGRIDSOHO |
| FX Vanna Multi | FXVANNAMLT |
| FX Multi Vega (Global) | FXATMMWINGGLOB |
| FX Bufga (Soho) | FXFULLBUFGASOHO |
| FX Revga (Soho) | FXFULLREVGASOHO |
| FX Bufga (MAD) | FXBUFGAWING |
| FX Revga (MAD) | FXREVGAWING |
| FX Exposure (Switcher) | V_FXEXPO_SWITCH |
| FX Embedded (Soho) | EMBEDDED_SOHO |
| CO Delta Cash | CODELTACASH |
| CO Gamma Cash | COGAMMACASH |
| CO Cross Gamma | COCROSSGAMMA |
| CO Vega BS REL | COVEGABSREL |
| CO Repo Pillar Projection | COREPOBUCKETPJC |
| Credit Spread Delta (Child) | DFSRATE |
| Credit Spread Delta Not Eq | DFSSPRD |
| CR Cross Gamma | CRSP_X_GAM |
| CR Delta Adj 1% | V_CRSPDEL_SN |
| CR Delta Adj Idx % | V_CRSPDEL_IDX |
| CR Gamma 1% | V_CRSPGAM_SN_1% |
| CR Gamma Index Scal | V_CRSPGAM_IDX_S |
| CR SP1% | V_P_SP1% |
| Index Skew Delta | CRDIDXSKEWDELTA |
| INF ZC Delta | IFDELTA |
| INF ZC Spread | IFSPREAD |
| OAS | OAS |
| OAS Shifted YC | OAS01SHIFTYC |
| OAS Gamma +10 | OASGAMMA+10 |
| Bond Spread | V_BSPREAD |
| Bond Basis (RF) Delta | BND_BASISPARENT |
| Bond Basis Delta Not Eq | BNDBASDELT_NTEQ |
| Future Security Basis | FUT_SEC_BASIS |
| Treasury Spread (Excl. Bond Curve) | V_TSYSPRD_EXC |
| Repo Spread | REPOSPRD |
| FVA Spread | FVASPRD |
| CC Duration 15Y | CC15YDV01 |
| CC Duration 30Y | CC30YDV01 |
| Security Position (EUR) | V_SECPOS_EUR |
| MRTG Rate Duration | MRTGRATEDV01 |
