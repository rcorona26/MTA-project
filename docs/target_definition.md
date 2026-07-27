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

An entire event is excluded if any of its updates contains one of these explicit
planned/scheduled-service status tokens:

- `planned-work`
- `weekday-service`
- `weekend-service`
- `saturday-schedule`
- `sunday-schedule`
- `essential-service`
- `no-scheduled-service`

The rule intentionally uses structured status values rather than fragile text
classification. A future labeled audit should measure false inclusions and
exclusions from this policy.

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
