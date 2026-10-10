# Director Session Log

- Session: `2026-10-10-bill-tracker-third-stage`
- Project: `bill_tracker_factory_v1`
- Live verification date: 2026-10-10
- Review state: `pending_human_review`
- Publication enabled: false
- Publishing allowed: false
- Scheduling state: not requested / not approved

## Source batch

Validated production pointer resolved through the existing generic factory:

- batch: `scheduled-weekly-37154732444-1`
- mode: `batch`
- promoted: `2026-10-06T02:15:58+00:00`
- manifest status: `validated`
- prior batch: `manual-monthly-37154194927-1`

Inventory probe run: `38081309065`.

## Production inventory

Production contains 89 Bills whose latest available `silver_bill_stages` row is `Committee Stage` with `stage_outcome=Current`.

The 89-row formal backlog is not treated as a single editorial edition. It includes restored and older Private Members' Bills as well as recent Government and Private Members' Bills. For the recurring series, selection should be change-driven: newly entering Third Stage or receiving meaningful new Third Stage activity.

Recent production-marked entrants/activity include:

- Social Welfare, Civil Registration and Charities (Amendment) Bill 2026, 84/2026, Dáil Third Stage from 2026-09-22.
- Seller's Legal Pack for Property Buyers Bill 2021, 150/2021, Dáil Committee Stage order/activity 2026-09-23.
- Strategic Lawsuits against Public Participation Bill 2026, 76/2026, referred to Select Committee on 2026-09-29.

## Production/live discrepancies

- Broadcasting (Amendment) Bill 2026, 54/2026, is absent from the production Current Committee Stage inventory even though official Oireachtas records show Committee Stage consideration on 2026-09-22 and the Bill remains before Dáil Éireann. This is recorded as a production snapshot gap.
- The production formal inventory contains many older restored Bills. Their `Current Committee Stage` marker is valid parliamentary state but does not necessarily indicate recent committee activity. Editorial selection must therefore verify live activity separately.
- Current official schedules show Public Health (Tobacco Products and Nicotine Inhaling Products) (Amendment) Bill 2026 and Media Regulation Bill 2026 scheduled for Seanad Committee Stage on 2026-10-14. These should be re-verified on their official Bill pages before inclusion in a final carousel.

## Third Stage semantics

Official Oireachtas procedure confirms Third Stage is Committee Stage. A Bill is considered section by section and amendments may be made. In the Dáil this is commonly done by a select committee, while Seanad Committee Stage is normally taken by the House. Agreed amendments change the Bill text; rejected/negatived amendments do not; amendments may also be withdrawn, not moved or ruled out of order. Recorded divisions are proposition-specific and do not establish overall support for the Bill. The normal next stage is Fourth/Report Stage.

## Prototype choice

Recommended prototype: Broadcasting (Amendment) Bill 2026, 54/2026.

Reason: layout/data complexity only. The 2026-09-22 Committee Stage includes substantial amendment activity, an amended Bill, agreed and withdrawn amendments, lost amendments, an amendment ruled out of order, and a certified amendment division lost 4 Tá to 5 Níl. It also tests the production/live discrepancy treatment.

## Prototype hierarchy

1. WHAT THE BILL DOES
2. WHAT HAPPENED AT THIRD STAGE
3. KEY AMENDMENT ACTIVITY
4. PRACTICAL EFFECT
5. WHERE IT IS NOW / WHAT HAPPENS NEXT

A separate member-vote visual is not used in the first prototype. The recorded division is noted only as an amendment-specific procedural fact. If a later full post includes a vote slide, the exact proposition must be certified before member votes are mapped.

## Proposed first-edition grouping

The recommended content model is recent/change-driven rather than attempting to cover all 89 formal backlog Bills.

Provisional Post 1: Broadcasting (Amendment) Bill 2026; Social Welfare, Civil Registration and Charities (Amendment) Bill 2026; Strategic Lawsuits against Public Participation Bill 2026.

Expected Post 1: 7 slides if Broadcasting receives a dedicated amendment-detail slide: cover, Broadcasting summary, Broadcasting amendment detail, Social Welfare summary, SLAPP summary, process glossary, Third Stage glossary.

Provisional Post 2: Seller's Legal Pack for Property Buyers Bill 2021 plus two current Bills that are re-verified as being at Third Stage after the latest live schedule transition. Candidate current-stage checks include Media Regulation Bill 2026 and Public Health (Tobacco Products and Nicotine Inhaling Products) (Amendment) Bill 2026.

Expected Post 2: 6 slides if all three Bills remain compact: cover, three Bill slides, process glossary, Third Stage glossary. This remains provisional until the live Bill pages confirm the two scheduled Seanad Committee Stage transitions.

## Design decisions

- Preserve the canonical Bill Tracker 1080x1350 visual family.
- Preserve dark green, cream and gold palette, corner ornaments, panel grammar and official source footer.
- Use shared-fit typography across comparable information boxes.
- Keep explicit overflow assertions.
- Third Stage slides use stage-dependent density and do not copy First Stage one-slide-per-Bill rigidly.
- Publication remains disabled.

## Approval state

Prototype direction is awaiting human review. No full carousel, caption, publication artifact or schedule is approved.
