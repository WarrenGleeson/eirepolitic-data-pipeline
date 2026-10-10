# Third Stage mockup review V2

- User feedback date: 2026-10-10
- Final V2 render run: `38086827757`
- Preview branch: `previews/bill-tracker-third-stage-mockups-v2`
- Preview commit: `0528a4ca8abb4e48361abf167d8f23a8ccac137b`
- Hosted review: `https://raw.githack.com/eirepolitic/Eirepolitic-data-pipeline/previews/bill-tracker-third-stage-mockups-v2/index.html`
- Review state: `pending_human_review`
- Publication enabled: false
- Publishing allowed: false

## User feedback on V1

The user identified formatting overlaps and felt the slides were not engaging enough or sufficiently informative about what Third Stage actually added.

## Visual review findings

The V1 contact sheet confirmed:

- a real text collision on the Broadcasting amendment slide;
- body copy that was too small and paragraph-heavy;
- weak hierarchy between Bill summary and Committee Stage activity;
- excessive empty panel space without a strong editorial takeaway;
- internal editorial/research language appearing on audience-facing Social Welfare and SLAPP slides;
- insufficient visual emphasis on Third Stage itself.

## V2 changes

- Added a reusable left-to-right process strip with Third Stage highlighted.
- Added one strong audience-facing hero statement per Bill.
- Replaced most paragraphs with short bullets.
- Added explicit Committee Stage result and next-stage treatment for substantive Bills.
- Added a `WHY THIS MATTERS` explanation for Broadcasting so the reader understands that Committee Stage changed the actual Bill text.
- Rebuilt the Broadcasting amendment slide into separate amendment cards with clear outcome labels.
- Separated amendment-title and detail columns to remove overlap.
- Preserved the amendment-specific vote safeguard: the 4 Tá / 5 Níl division is explicitly described as a vote on one amendment, not the Bill as a whole.
- Reframed thin-record Bills as clear status slides with `WHAT WE KNOW AT THIRD STAGE`, `WHAT TO WATCH FOR NEXT`, and `BOTTOM LINE`, rather than exposing internal editorial notes.
- Retained 1080x1350 dimensions, canonical Bill Tracker palette, corner ornaments, source footer, shared-fit text sizing and explicit overflow assertions.

## Visual verification

The four PNGs from preview commit `0528a4ca8abb4e48361abf167d8f23a8ccac137b` were visually inspected after the successful factory render.

- Broadcasting summary: clean layout, no overlap, Third Stage process and outcome clear.
- Broadcasting amendments: amendment cards and division panel clean, prior title/detail collision resolved.
- Social Welfare: clean compact status treatment, no internal editorial instructions exposed.
- SLAPP: clean compact status treatment, concise copy and no overflow.

No diagnostic placeholders are present in the final V2 review.

## Approval state

V2 mockup direction is awaiting human feedback. No full carousel, caption, publication artifact or schedule is approved.
