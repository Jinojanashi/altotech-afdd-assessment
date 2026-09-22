# Screenshot evidence walkthrough

Run `make demo`, use a desktop viewport around 1440×900, and capture in this order. Keep IDs, timestamps,
units, and state labels visible; do not include `.env`, terminals containing secrets, or provider headers.

1. `01-portfolio-health.png` — `/portfolio`, showing API health and accepted/duplicate/rejected counts plus the three properties.
2. `02-hero-issue.png` — the `ahu-a-f02-east` Critical issue header, recovered status, exact rule version, threshold, and duration.
3. `03-trigger-evidence.png` — SAT/SAT_SP trend and evidence rows with RUN, difference, quality, and the 10:15 opening boundary.
4. `04-issue-timeline.png` — 10:00 qualification, 10:15 opening, and 10:21 recovery in one frame.
5. `05-topology-separation.png` — `building-a-plant-room` under Installed at, served zone, and the two affected occupied rooms side by side.
6. `06-rule-preview.png` — rule version configuration, matched targets, and at least one exclusion reason.
7. `07-building-b-override.png` — Building B’s effective 2.0°C local override in rule preview.
8. `08-ai-review-before-confirm.png` — `READY_FOR_REVIEW`, interpreted draft, non-empty target preview, and enabled confirmation button before it is clicked. Capture only after a successful configured provider run.
9. `09-ingestion-exceptions.png` — `/ingestion/status` and `/ingestion/events` showing one duplicate and one rejected unknown device (two browser panes are acceptable).

Screenshots 2–5 form a sequenced investigation: symptom, measured trigger, lifecycle, then physical versus
affected topology. Screenshot 8 is pending the required successful real-model run; a provider `FAILED` screen
must not be substituted or labeled as successful review evidence.
