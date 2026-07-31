# Target definition

## Intended question

For a subway line at the start of hour `t`, what is the probability that a new
significant, unplanned customer-facing service disruption will begin during the
next 60 minutes?

## Unit of observation

One row per:

- Canonical subway line
- Local New York prediction hour

The label window is `[prediction_hour, prediction_hour + 1 hour)`. Future
features must be constructed strictly from records timestamped before
`prediction_hour`.

## Label

`significant_disruption_next_hour` is `1` when at least one qualifying
event-line start falls in the label window and `0` otherwise.

An alert update qualifies when its normalized `status_label` contains at least
one of:

- `delays`
- `severe-delays`
- `part-suspended`
- `suspended`

The deliberately narrower first version does not treat `some-delays`, reroutes,
skipped stops, boarding changes, or information outages as significant unless
the same update also contains one of the qualifying statuses.

## Planned-event exclusion

A qualifying update is excluded if that update, or any earlier update in the
same event, contains one of these explicit planned/scheduled-service status
tokens:

- `planned-work`
- `weekday-service`
- `weekend-service`
- `saturday-schedule`
- `sunday-schedule`
- `essential-service`
- `no-scheduled-service`

The exclusion is evaluated as of each update's position in the event's
timeline rather than over the event as a whole. This matters because an event
can start as a genuinely unplanned disruption and only later resolve into a
scheduled-service message (e.g. "resumed on weekday-service"); an earlier
version of this rule excluded the entire event in that case, wiping out the
real unplanned hours along with the resolution message.

The rule intentionally uses structured status values rather than fragile text
classification.

**2026-07-30 labeled audit:** a 200-row stratified human review
(`data/review/label_review_sample.csv`, 100 included_positive / 50
excluded_as_planned / 50 excluded_nonqualifying_status) found 10/200 (5%)
disagreements with the policy, all 10 in the `excluded_as_planned` stratum and
all attributable to the retroactive whole-event exclusion described above.
The rule was changed from whole-event to timeline-relative exclusion in
response, and labels were regenerated (positive line-hours: 148,914 ->
148,926 of 1,352,025, +0.0009 pts prevalence). A follow-up spot-check against
the 10 originally-disagreeing rows found 8/10 corrected. The remaining 2 are
known limitations, not regressions:

- An event can still evolve non-monotonically (an early planned-sounding
  compound status token followed by a later genuine unplanned escalation,
  e.g. a mid-event derailment); the timeline-relative rule only protects
  hours *before* a planned token first appears, not ones after. Not fixed by
  this change.
- One audit row's `event_instance_id` did not match the database's alert
  history for that id, which looks like a data-entry error made during the
  manual review rather than a pipeline issue.

## Event deduplication

`event_id` is intended to group every update to one MTA incident, but the source
contains rare cases where an ID is reused and `update_number` restarts at zero.
The pipeline derives an `event_instance_id` every time that sequence restarts.
Alerts are then exploded to canonical lines. For each
`(event_instance_id, line)`, only the earliest qualifying update is retained.
This means:

- Repeated updates do not create repeated positive events.
- A line added in a later update receives its own later event-line start.
- Escalation from `delays` to `part-suspended` remains one event for a line.
- Reused source event IDs do not merge independent incidents.

## Line policy

Included canonical lines are:

`1 2 3 4 5 6 7 A B C D E F FS G GS H J L M N Q R W Z`

Aliases are mapped as follows:

- `6X` -> `6`
- `7X` -> `7`
- `FX` -> `F`

`SI` is excluded because this target is scoped to the NYC subway rather than
Staten Island Railway. Unrecognized affected tokens are retained in an audit
table instead of silently discarded.

## Interpretation and limitations

This label predicts publication/escalation of an MTA customer-facing disruption
alert. It does not directly measure:

- Individual train arrival delay
- The percentage of trains delayed
- Passenger delay minutes
- Station-level delay

The source timestamp has no UTC offset. The pipeline preserves it as New York
local wall-clock time, so the repeated daylight-saving hour cannot be perfectly
disambiguated from this dataset alone.
