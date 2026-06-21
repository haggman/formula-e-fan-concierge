# Energy management

**Topic:** Energy / battery management · **Scope:** Formula E Gen3, Berlin 2024 E-Prix (Season 10)

Energy management is the heart of Formula E strategy. Every car starts with a fixed amount of usable battery energy for the race and **cannot refuel or swap batteries** — so a driver's job is to complete the full race distance as fast as possible without running the battery flat before the flag. This turns a Formula E race into a rolling arithmetic problem: lift-and-coast into corners, harvest energy under braking, slipstream rivals to save power, and time pushes so the car arrives at the finish with as little energy left "on the table" as possible.

In the Berlin dataset, per-lap energy is expressed as **`percent_consumed` — each lap's share of the car's total race energy allocation**, normalized so that a finisher's laps **sum to exactly 100** over the race. This is an important data-reading subtlety: mid-race, a car spending more than the field average on a given lap is genuinely over-spending, but because every finisher's total is forced to 100 by construction, **comparisons at or near the final lap converge for everyone and stop being meaningful** — the signal is in the mid-race deltas, not the end.

The headline number fans hear — "X% energy remaining" — is the inverse of cumulative consumption. A car reported at 36% remaining late in the race has used about 64% of its allocation and is managing the rest to the finish. Converting percentages to kWh uses the race energy allocation; the Gen3 usable figure is in the high-30s kWh range, and the dataset's per-lap percentages are the more reliable currency for reasoning about who is up or down on energy.

A key Gen3 wrinkle is **regeneration**. The Gen3 car recovers energy under braking through both axles and can put a large amount back into the battery, so under a **safety car or full-course yellow** — when cars are slow and braking gently but still harvesting — net consumption can briefly go **negative** (the car puts back more than it draws). That is why safety-car periods are strategically golden: they let the field "bank" energy and reshape the rest of the race.

**Quick facts:** fixed race energy, no refuelling/swaps · `percent_consumed` per-lap, sums to 100 for finishers · mid-race deltas are signal, end-of-race convergence is not · regen can make consumption negative under safety car.
