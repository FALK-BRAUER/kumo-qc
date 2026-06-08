# George Context Trade Diagnostics

Baseline for entry deltas: `industry_top3_focus`.

## Variant Diagnostics

| Variant | Return % | DD % | Buys | Closed | Open | Net PnL | Realized PnL | Implied Open PnL | Worst |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| entry_gapvol_base | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| entry_gapvol_vol125 | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| entry_gapvol_vol150 | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| exit_kijun_phase3_base | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| exit_cloud_adherence | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| exit_weekly_kijun | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| exit_proactive_target_06 | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| exit_proactive_giveback_tight | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| exit_scratch_flat_3d | 27.813 | 20.2 | 37 | 21 | 16 | 27813.00 | -17687.29 | 45500.29 | MRVL -1805.770 |
| industry_top3_focus | 27.695 | 19.4 | 36 | 19 | 17 | 27695.00 | -15099.39 | 42794.39 | MRVL -1805.770 |
| industry_top8_broad | 27.695 | 19.4 | 36 | 19 | 17 | 27695.00 | -15099.39 | 42794.39 | MRVL -1805.770 |
| industry_bct_share_heavy | 27.695 | 19.4 | 36 | 19 | 17 | 27695.00 | -15099.39 | 42794.39 | MRVL -1805.770 |

## Largest Entry-Set Deltas

| Variant | Added | Missed | Same Entries | Added Symbols | Missed Symbols |
|---|---:|---:|---:|---|---|
| entry_gapvol_gap05 | 38 | 35 | 1 | ABVX ACHR ARM ATI AU BABA BITX C COHR CONL CRS CRWD DKNG DOV EAT EBAY GE GGLL KGC LEU MP NEM NFLX NRG OSCR PAAS RIOT RTX SBUX SMR TSM U UBER URA USO VFC VST XPEV | ABT AIG AR ATI AU BITX BJ BKR BSX CEG EBAY EZU GLW HOOD HPE IBIT JLL KGC KLAC META MP MRVL NEM NTES PAAS QBTS RBLX RUN SHOP SPOT TSM UAL URBN USO VST |
| entry_gapvol_gap04 | 33 | 30 | 6 | ACHR AR ARM ATI AU BITX BTI C EAT EBAY FIX HPE ILMN KGC META MP MS NEM NFLX NOC NRG NXT OSCR PAAS QBTS RTX SHOP SMR TSM UAL URA URBN USO | ABT AIG AR ATI AU BITX BJ BKR EBAY EZU GLW HPE IBIT JLL KGC META MP MRVL NEM NTES PAAS QBTS RBLX RUN SHOP SPOT TSM UAL URBN USO |
| attention_floor_05 | 24 | 24 | 12 | AIG AR ARM ATI AU BJ BKR BTI C CCJ EBAY EQT GLW HAS KLAC MP NEM NOC NRG NU NXT SAP SATS UAL | ABT AIG AR ATI AU BITX BJ BKR EBAY EZU GLW IBIT JLL KGC KLAC MP NEM NTES PAAS QBTS RUN UAL URBN USO |
| entry_gapvol_window60 | 22 | 20 | 16 | ACHR AIG ATI AU BCS BTI CEG GLW GOOG GOOGL HOOD HPE MP NEM NET NTES NXT PAAS QBTS RUN SPOT URBN | ABT AIG ATI AU BKR CEG GLW HOOD HPE JLL KGC LNG MP NEM NTES PAAS QBTS RUN SPOT URBN |
| attention_ticker_heavy | 19 | 18 | 18 | ACHR AR AU BCS BJ BKR BTI C EBAY EZU GLW IBIT KGC MP NEM NXT PAAS RUN USO | ABT AR AU BITX BJ BKR EBAY EZU GLW IBIT JLL KGC MP NEM PAAS QBTS RUN USO |
| entry_gapvol_base | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |
| entry_gapvol_vol125 | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |
| entry_gapvol_vol150 | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |
| exit_kijun_phase3_base | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |
| exit_cloud_adherence | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |
| exit_weekly_kijun | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |
| exit_proactive_target_06 | 8 | 7 | 29 | ACHR AIG BCS BTI NXT QBTS RUN URBN | ABT AIG JLL NTES QBTS RUN URBN |

## Readout

- Most industry, carry, volume, and exit variants preserve the same entry set as the baseline or the intraday gap-vol base.
- All completed/closed trades are losers in this FY2025 pack; positive net return is carried by open year-end positions.
- The George attention variants add entries but do not improve the realized loss profile.
- Strict gap/window entry variants rotate into a materially different entry set and are the main source of poor results.
- Exit variants matching the same closed/open trade set confirm that their configured thresholds did not bind in FY2025.
