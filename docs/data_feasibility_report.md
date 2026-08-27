# Line-hour target feasibility report

## Result

The official MTA Service Alerts archive supports construction of the proposed
line-hour **service-disruption proxy target**. It does not by itself support a
measured individual-train lateness target.

All hard pipeline checks passed on the full verified snapshot.

## Snapshot provenance

| Item | Value |
|---|---|
| Dataset | MTA Service Alerts: Beginning April 2020 |
| Socrata ID | `7kct-peq7` |
| Agency filter | `NYCT Subway` |
| Maximum alert ID | `525218` |
| Source maximum timestamp | `2026-06-29 23:57:00` local wall time |
| Downloaded rows | 285,896 |
| SHA-256 | `a5c064e11cc8ebf5be4cbc659e31de2584579b357ab18911b7a90d30aa64f7b7` |
| Complete target coverage | 2020-04-28 14:00 through 2026-06-29 23:00 local |

## Target volume

| Measure | Result |
|---|---:|
| Source alert updates | 285,896 |
| Source event IDs | 113,104 |
| Derived event instances | 113,106 |
| Qualifying event-line starts | 165,479 |
| Complete hours | 54,081 |
| Canonical subway lines | 25 |
| Line-hour rows | 1,352,025 |
| Positive line-hours | 148,914 |
| Negative line-hours | 1,203,111 |
| Overall positive prevalence | 11.014% |

Four qualifying event-line starts fall in the incomplete first or last source
hour and are intentionally absent from the complete-hour target table.

## Positive prevalence by line

| Line | Positive line-hours | Prevalence |
|---|---:|---:|
| 1 | 6,698 | 12.39% |
| 2 | 10,717 | 19.82% |
| 3 | 6,781 | 12.54% |
| 4 | 9,141 | 16.90% |
| 5 | 7,302 | 13.50% |
| 6 | 8,445 | 15.62% |
| 7 | 3,832 | 7.09% |
| A | 12,228 | 22.61% |
| B | 4,874 | 9.01% |
| C | 6,524 | 12.06% |
| D | 9,194 | 17.00% |
| E | 7,204 | 13.32% |
| F | 10,632 | 19.66% |
| FS | 320 | 0.59% |
| G | 2,428 | 4.49% |
| GS | 193 | 0.36% |
| H | 2,776 | 5.13% |
| J | 3,787 | 7.00% |
| L | 3,785 | 7.00% |
| M | 4,563 | 8.44% |
| N | 8,746 | 16.17% |
| Q | 7,115 | 13.16% |
| R | 8,017 | 14.82% |
| W | 3,361 | 6.21% |
| Z | 251 | 0.46% |

The overall target is not extremely imbalanced, but the shuttle and Z targets
are rare. Model evaluation must include per-line metrics and calibrated
probabilities rather than relying on overall accuracy.

## Source-quality findings

1. Two `(event_id, update_number)` keys are duplicated because the source
   reuses two event IDs with a new update-zero record. The pipeline derives a
   new `event_instance_id` when the update sequence restarts.
2. Some alerts list both a base line and express alias, such as `6 | 6X`.
   Canonical lines are deduplicated after alias mapping.
3. There are 2,360 unmapped affected-token assignments: 2,357 are `SI`, two are
   `D99`, and one is `SIM7`. They remain auditable and do not become subway
   target rows.
4. The source timestamp lacks a UTC offset, so the repeated daylight-saving
   hour cannot be unambiguously separated.
5. The current target grid includes every line during every complete hour. It
   does not yet identify hours when a line had no scheduled service. Static
   GTFS schedule eligibility must be added before model training.
6. The structured planned-event exclusion identified 3,319 event instances.
   A manually reviewed label sample is still required to estimate proxy-label
   precision and recall.

## Feasibility decision

Proceed to a feature and baseline milestone, subject to two gates:

1. Join static GTFS schedules so inactive line-hours are excluded or explicitly
   marked.
2. Manually audit a stratified sample of positive and negative event windows to
   validate the significant/unplanned status policy.

Only after those gates should classifier performance be interpreted.
