# Notes for Andy and Robert

*Left for you before you start drafting the report. Read this first — it will
save you from writing the wrong paper.*

---

## Where you actually are

Better than you think, and not where you think.

You have built the part that most projects at this level skip: a **reproducible,
auditable data layer**. An immutable snapshot with a SHA-256 manifest, seven
declared SQL layers, a quality report, a passing `integrity_check`, and a
200-row hand audit of the labels. When I read student work, this is the section
that is almost always missing, hand-waved, or quietly done in a notebook that no
longer runs. Yours runs from a clean checkout. Do not undersell it.

What you have *not* built is a good predictor. Let us be precise about that,
because precision is the whole point:

| | |
|---|---|
| PR-AUC (gradient boosting) | 0.2566 |
| Precision at the tuned threshold | 0.2381 |
| Test base rate | 0.1440 |
| Lift | **1.65×** |

A 1.65× lift is a real effect. It is not a useful product. Both halves of that
sentence belong in your report, in that order.

## The finding that should anchor the paper

Do not lead with the PR-AUC. Lead with **what the model turned out to be made
of**, because that is the intellectually interesting result and it is one you
can defend.

The top two permutation importances are the line's own trailing 30-day
disruption rate and the hour of day. The new predictor on the dashboard lets you
demonstrate this rather than assert it, and I want you to use it:

- The **A** with its real recent history scores **0.637**. The 42nd St shuttle
  scores **0.012**.
- Freeze the history at a generic hour so only the one-hot line indicator
  changes, and those same two lines score **0.393** and **0.260**.

Identity is worth ~0.13 of separation. History is worth roughly twice that. So
the model has not learned *that the A is the A*. It has learned *that the A has
been breaking down lately* — which is a trailing average wearing a machine
learning costume. That is your thesis. It is a more honest and more publishable
finding than "we got 0.2566."

## Three traps I want you to avoid

**1. Do not call the output a probability.** It is not one, and you now have the
calibration curve to prove it. Hours scored 0.76 see disruption 31% of the time.
`class_weight="balanced"` inflates minority scores by construction. The scores
*rank* hours usefully; they do not *quantify* risk. If either of you writes "a
76% chance of delay" I will find it. The predictor deliberately labels its big
number "model score" and puts the historically observed rate beside it — mirror
that discipline in your prose.

**2. Do not let the target quietly become "delays."** Your label fires when the
MTA *publishes a qualifying unplanned alert*. That is a measure of the agency's
communication behavior, not of train movement. This matters more than it sounds:
your base rate drifts from ~7.7% in early 2021 to ~15.4% by April 2026, and a
change in alerting policy is at least as plausible an explanation as a genuine
doubling of subway dysfunction. You cannot distinguish those with this dataset.
Say so plainly, in the limitations section, and do not let a reader walk away
thinking you measured reliability.

**3. Do not claim your model would help a rider.** At the tuned operating point
it is wrong about three times in four. Drag the threshold on the dashboard and
you will see there is no setting that rescues this — push precision to 32.5% and
recall collapses to 1.7%. That trade-off curve *is* the argument. Show it.

## The threshold section is your best rhetorical asset

Most student reports present one operating point as if it fell from the sky. F1
is an arbitrary tiebreaker — it asserts that a missed disruption and a false
alarm cost exactly the same, which nobody believes and nobody stated. The
interactive threshold explorer lets you make that critique explicit and then let
the reader resolve it themselves. Use it as the centerpiece of your evaluation
section, and say in the text that the choice is a policy question you are
deliberately declining to make on the reader's behalf.

## On the dashboard itself

It embeds the real 300-tree model and runs it in the browser. Two things follow
that you should both understand before you present it, because you *will* be
asked:

- It is **exact**, not an approximation — verified against scikit-learn to
  3×10⁻⁹ at export time, and the export refuses to write a bundle that fails
  the check. If someone asks "is that the real model or a lookup table," the
  answer is the real model.
- There is **no server**, which is why it can live on GitHub Pages for free and
  will still work in two years when whatever free tier you would have used has
  been discontinued.

One implementation detail worth knowing, because it bit me: the split thresholds
must be exported at full float precision. Rounding them to six decimals is not a
rounding error — a threshold sits exactly at a real data value, so shaving a
decimal flips the comparison and sends the row down a completely different
subtree. It moved test predictions by up to 0.036. There is now an assertion
guarding this. Do not "tidy" it away to save file size.

## Web development notes for Andy and Robert

*Putting on my web-development-professor hat for this section: the dashboard is
part of your argument, not decorative packaging around it.*

**Andy:** you own the reader's path through the page. The first screen now does
the right work: it states the conclusion, defines the target, shows the operating
metrics, and places the responsible-use warning beside them. Preserve that
hierarchy. Do not replace the conclusion with a generic project title, move the
warning to the footer, or add a splashy hero that delays the evidence. A recruiter
should understand the result in under a minute; a professor should be able to
find the methodological qualification without hunting for it.

**Robert:** you own the contract between the data exports and the interface.
`docs/dashboard_template.html` is the source; `docs/dashboard.html` is generated.
If you edit the generated file directly, the next build will erase your work.
Likewise, the feature order, full-precision split thresholds, score histograms,
and profile data are model artifacts, not convenient front-end constants. When a
number in the prose disagrees with the embedded bundle, investigate and disclose
the disagreement rather than forcing the interface to reproduce the prose.

**Both of you:** the identity-versus-history comparison is the visual thesis of
the project. Be ready to explain what each pair holds constant. "Profile on"
loads a line's typical historical conditions; "profile off" freezes the current
conditions and changes only line identity. If that switch ever changes hidden
history values while it is off, the comparison is no longer valid even if the
screen still looks convincing.

### What I would check in a code review

- **Semantics before styling.** Keep one `h1`, a real `nav`, labeled controls,
  ordered headings, buttons for actions, and live regions only for results that
  actually change. A keyboard user must be able to reach every interaction and
  see where focus is.
- **Mobile is a requirement, not a shrink pass.** Test at 375–390 px after every
  structural change. The page must not scroll horizontally; route controls,
  confusion-matrix labels, charts, and technical tables all need deliberate
  small-screen behavior.
- **Color is supporting information.** MTA route colors may identify a series or
  line, but the route letter, label, and value must remain available without
  color. Never turn the dashboard into an unlabeled subway-map motif.
- **Scores are not probabilities.** Search the rendered page for "probability,"
  "chance," and "risk percentage" before presenting. Those terms are acceptable
  only when explicitly explaining why the raw score cannot be read that way.
- **Static means genuinely static.** A successful review build should make no
  CDN, font, analytics, image, or API requests. Test the generated artifact, not
  just the template, and keep GitHub Pages deployment boring.
- **Interaction claims need regression tests.** At minimum, guard the 0.58
  operating point, browser-equivalent tree traversal, profile-switch behavior,
  feature order, drift-band dates, and complete placeholder replacement.

### Presentation advice

Do not demo every chart. Start with the key finding, use the threshold explorer
to show why no operating point rescues the model, then use the live predictor to
separate line identity from recent history. Open the detailed evidence only when
the audience asks how you know. That sequence demonstrates both technical depth
and editorial judgment—which is what a strong portfolio project should do.

One last grading note: polish is not the same as complexity. The strongest
front-end decision here is that a half-megabyte static file can explain and run a
300-tree model without a framework or server. Keep the implementation legible,
keep the claims narrower than the evidence, and resist adding technology merely
to make the stack sound larger.

## Suggested division of labor

Robert — you own the data and target sections. You have the strongest claim to
the reproducibility story, and the label audit is yours to write up. Include the
disagreement rate from the 200-row sample; a stated error rate is worth more
than a claim of correctness.

Andy — you own evaluation and limitations. Build the argument around the
threshold curve and the identity-versus-history experiment above. The
limitations section should be the strongest part of the paper, not an apology
tacked to the end.

Both of you: write the abstract last, and make sure it contains the word
"modest."

## If you want to actually improve the model

Only after the report is drafted. In rough order of expected payoff:

1. **Calibration** — Platt scaling or isotonic regression on the validation
   split. Cheap, and it converts your scores into something you are allowed to
   call a probability.
2. **The alert text.** You are sitting on `header` and `description` fields and
   using none of it. Even a bag-of-words over recent alerts would inject the
   dynamic signal the current features lack.
3. **Line adjacency.** Lines sharing track should share risk. The G going down
   tells you something about the F. Nothing in the current feature set knows
   that.
4. Weather. Obvious, external, and probably the largest single omission.

Do not add more trailing-rate windows. That well is dry — you have already
demonstrated it.

---

*Reproduce everything with:*

```bash
mta-alerts build --replace      # ~35s
python train_classifier.py      # ~45s
python export_dashboard_data.py # metrics + curves
python export_model_bundle.py   # trees + threshold histograms (asserts fidelity)
python build_dashboard.py       # -> docs/dashboard.html
```
