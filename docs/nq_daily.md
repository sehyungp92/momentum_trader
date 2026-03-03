### Part 1: Contract List & Roll Schedule (The Foundation)

To cover the last 2 years (early 2024 to early 2026), your script must iterate through these specific contracts. NQ rolls on the **third Friday** of the month, but the "liquidity switch" (where you should roll your data) typically happens on the **Monday prior**.

| Contract Code | Expiration Month | Liquidity Roll Date (Switch here) |
| --- | --- | --- |
| **NQH4** | March 2024 | March 11, 2024 |
| **NQM4** | June 2024 | June 10, 2024 |
| **NQU4** | September 2024 | September 16, 2024 |
| **NQZ4** | December 2024 | December 16, 2024 |
| **NQH5** | March 2025 | March 17, 2025 |
| **NQM5** | June 2025 | June 16, 2025 |
| **NQU5** | September 2025 | September 15, 2025 |
| **NQZ5** | December 2025 | December 15, 2025 |
| **NQH6** | March 2026 | March 16, 2026 (Upcoming) |

---

### Part 2: Detailed Instructions for Claude Code

Copy and paste this prompt into Claude to generate the core logic:

> "Act as an expert quantitative developer. Write a Python script using `ib_insync` to build a synthetic, back-adjusted 2-year historical data series for NQ futures.
> **Requirements:**
> 1. **Data Pulling:** Do NOT use `ContFuture`. Instead, iterate through the individual quarterly contracts from NQH4 through NQH6.
> 2. **Handling IBKR Limits:** For each contract, download data in 6-month chunks (for intraday) or 1-year chunks (for daily). Use `includeExpired=True`.
> 3. **Strict Pacing:** Implement an 11-second `time.sleep()` between every `reqHistoricalData` call.
> 4. **Stitching Logic:** Stitch contracts on the Monday of the expiration week. At the switch point, identify the 'Price Gap' (New Contract Open - Old Contract Close).
> 5. **Panama Adjustment:** Apply a cumulative adjustment. When moving backward, subtract the gap from all previous history so the price series remains seamless (no vertical jumps at rolls).
> 6. **Output:** Return a single cleaned DataFrame with a 'Date' index and 'Adjusted_Close' column, saved as NQ_BACKADJUSTED.csv."
> 
> 

---

### Part 3: The "Panama Adjustment" Logic (In Detail)

If you do not perform this adjustment, your backtester will think there was a massive profit or loss every three months.

1. **Find the Offset:** On the roll date (e.g., June 16, 2025), if NQM5 (June) closed at **19,000** and NQU5 (Sept) opened at **19,045**, the gap is **+45 points**.
2. **Back-Shift:** To keep the chart smooth, you must **subtract 45 points** from every single price bar in the NQM5 history (and all contracts before it).
3. **Cumulative Effect:** As you go back through 2 years (8 rolls), the "Adjusted Price" for early 2024 will look significantly different from the "Raw Price" at that time, but the **price action** (the relative moves) will be perfectly preserved.

### Part 4: Critical Troubleshooting for NQ

* **Tick Size:** Ensure your script recognizes the NQ tick size of **0.25**. Adjustments should be multiples of this.
* **Volume Check:** If you want to be more precise than a "Calendar Roll," tell Claude to compare the volume of the Front Month vs. the Next Month. Roll the data only when the Next Month's volume exceeds the Front Month's volume.
* **Trading Hours:** For NQ, I highly recommend downloading **Full Session** data (23 hours). Many NQ gaps occur during the European session or at the 6:00 PM EST open.

---