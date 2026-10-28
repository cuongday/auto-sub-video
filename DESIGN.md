---
name: Auto-Sub
description: A self-hosted Vietnamese video production line, run like a post-office counter.
colors:
  rail: "#1F3A2E"
  rail-2: "#274838"
  rail-hover: "#2B4D3D"
  rail-rule: "#36594A"
  rail-ink: "#E6F0E8"
  rail-muted: "#A3BDAD"
  rail-info: "#A9C8E4"
  rail-ok: "#92D7A9"
  rail-bad: "#F3A79E"
  post-yellow: "#F2C230"
  post-yellow-hover: "#E7B41C"
  post-yellow-ink: "#2A2105"
  post-yellow-deep: "#7A5B00"
  ground: "#EBF0E9"
  surface: "#F7F9F5"
  surface-2: "#E2E9DF"
  field: "#FCFDFB"
  rule: "#BFCBBE"
  rule-soft: "#D5DDD3"
  ink: "#17211B"
  ink-2: "#4A5A50"
  link: "#1F5A3E"
  ok: "#24693F"
  bad: "#B02E26"
  warn: "#8A5800"
  info: "#335A7A"
  on-bad: "#FFF6F4"
  plate: "#0C120F"
  plate-ink: "#E3ECE5"
  plate-info: "#93B6D6"
  spk-1: "#9A6200"
  spk-2: "#2F5D8A"
  spk-3: "#24693F"
  spk-4: "#A33C6B"
  spk-5: "#66489E"
  spk-6: "#B0441C"
typography:
  display:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.4
  stamp:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.06em"
    fontFeature: "\"tnum\""
  serial:
    fontFamily: "Be Vietnam Pro, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 500
    letterSpacing: "0.01em"
    fontFeature: "\"tnum\""
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "12.5px"
    fontWeight: 500
    lineHeight: 1.55
rounded:
  hair: "2px"
  stamp: "3px"
  base: "4px"
  large: "6px"
spacing:
  xxs: "4px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.base}"
    padding: "6px 12px"
    height: "32px"
  button-hover:
    backgroundColor: "{colors.surface-2}"
  button-primary:
    backgroundColor: "{colors.post-yellow}"
    textColor: "{colors.post-yellow-ink}"
    rounded: "{rounded.base}"
    padding: "6px 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.post-yellow-hover}"
  button-danger-solid:
    backgroundColor: "{colors.bad}"
    textColor: "{colors.on-bad}"
    rounded: "{rounded.base}"
    padding: "6px 12px"
  button-icon:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.base}"
    padding: "4px 6px"
    width: "32px"
  input:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.base}"
    padding: "6px 9px"
  segment-on:
    backgroundColor: "{colors.post-yellow}"
    textColor: "{colors.post-yellow-ink}"
    rounded: "{rounded.stamp}"
    padding: "5px 12px"
  stamp:
    textColor: "{colors.ink-2}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "2px 6px 1px"
  tally:
    textColor: "{colors.ink-2}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "4px 10px 3px"
  tally-on:
    backgroundColor: "{colors.post-yellow}"
    textColor: "{colors.post-yellow-ink}"
  rail-row:
    textColor: "{colors.rail-ink}"
    rounded: "{rounded.base}"
    height: "34px"
  rail-row-job:
    textColor: "{colors.rail-ink}"
    rounded: "{rounded.base}"
    height: "32px"
  modal:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.large}"
    width: "460px"
  media-plate:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.plate-ink}"
    rounded: "{rounded.base}"
---

# Design System: Auto-Sub

## Overview

**Creative North Star: "The Bưu điện Counter"**

Auto-Sub is the counter of a Saigon post office for videos. Every job, part and download is a numbered item (Số 0042) that gets stamped as it moves through the line: CHỜ, ĐANG CHẠY, XONG, LỖI, each with the time the stamp landed. A deep moss-green rail carries navigation and the tree of projects. The working area is green-tinted form paper, ruled with 1px hairlines like a printed form, not boxed into cards. Post yellow is the one voice for the primary action and for selection. State colours (ok green, postmark red, amber, ink blue) belong to stamps and the bars beside them.

The density is a working counter for long batch sessions on big screens. Rows are dense and one line high, figures are tabular so columns of serials, times and durations line up, and the page leads with the list. Settings sit in a right-hand column or fold away when a step is done. The video is the subject: every frame, poster, thumbnail and player sits on a near-black plate so the chrome never tints what the operator is judging.

The system rejects the category default of a grey dashboard with one neon accent, pill badges and floating cards. It also rejects decoration that does no work: there are no gradients and no shadows on resting surfaces.

**Key Characteristics:**
- Moss rail, green-tinted paper ground, near-black ink; post yellow only for the primary action and selection.
- State is always a postmark stamp: outlined, uppercase, rotated −2°, in the state's ink, with the time it changed.
- Every item in a list carries a four-digit serial ("Số 0042") in tabular figures.
- Sections are ruled by a hairline above them, not boxed.
- Media always sits on a dark plate with `color-scheme: dark`.
- Small 4px corners, 1px rules, flat surfaces. Only floating layers cast a shadow.

## Colors

The palette is a post office: moss-green paint, form paper, ink, a yellow letterbox and a red postmark. Every colour literal lives as a custom property in `frontend/src/styles.css` `:root`, and derived tints use `color-mix()` against those tokens.

### Primary
- **Post Yellow** (post-yellow): the primary button, the "on" state of tabs, segments, chips, tool buttons and tallies, the active rail section header, the rail's selected-row marker, the region-picker box and handles, and the focus ring on the rail. Its text partner is **Letterbox Ink** (post-yellow-ink). **Worn Yellow** (post-yellow-hover) is its hover and the "too long" length bar. **Deep Brass** (post-yellow-deep) is the dark variant for yellow-family text on paper.

### Secondary
- **Moss Rail** (rail): the navigation rail, the login screen, the audio story's header tile, the modal backdrop tint (55% mix) and the source of the dialog shadow. Checkboxes, radios and ranges on paper use it as `accent-color`. The rail family (rail-2, rail-hover, rail-rule, rail-ink, rail-muted) gives the rail its own hover, rule, text and muted text. rail-info, rail-ok and rail-bad are the light state inks for stamps drawn on the rail.

### Tertiary (state inks)
- **Ledger Green** (ok): done and approved stamps, finished steps and bars, success text.
- **Postmark Red** (bad): error, interrupted and cancelled stamps, destructive actions, error text and boxes. Solid fills pair it with **Red Paper** (on-bad).
- **Sealing-Wax Amber** (warn): awaiting-review stamps, warnings, "needs a look" flags, the stale banner's border.
- **Ink Blue** (info): running and queued stamps, progress bars, the active step dot, info notices.

### Neutral
- **Form Paper** (ground): the page ground. Light and slightly green, never cream.
- **Sheet** (surface): buttons, dialogs, the subtitle table, notices, popovers.
- **Carbon Sheet** (surface-2): hover fill for buttons and rows, table header, empty bar tracks, disabled fields.
- **Field White** (field): inputs, drop zones, the log, selectable cards.
- **Form Rule** (rule): every 1px hairline, input stroke and section rule. **Faint Rule** (rule-soft) divides rows inside a list.
- **Ink** (ink): text, the focus ring on paper, the playing-row marker. **Pencil** (ink-2): secondary text, labels, serials, new and waiting stamps.
- **Ledger Link** (link): text links.
- **Plate Black** (plate): the dark ground under every video, frame, poster and thumbnail. plate-ink and plate-info are the text and secondary-box colours on it.
- **Speaker inks** (spk-1 to spk-6): fixed per-speaker text colours on paper in the voices panel. They are data colours, not accents.

### Named Rules
**The Letterbox Rule.** Post yellow marks the one primary action in a header and what is selected or on. Among states it may only stand in for warning: on the rail the amber ink is remapped to yellow, and yellow tints back warning banners, the "Cần cấu hình" row and over-length bars. Running, done and error never turn yellow.

**The Rail Remaps Rule.** The rail re-points `--ink`, `--ink-2`, `--rule`, `--focus` and the state inks to rail values, so shared controls and stamps inside it read correctly without separate rules. Add rail controls by inheriting these variables, never by hard-coding light colours.

**The Plate Rule.** Anything that shows a video frame (player, picker, thumbnail, poster, scene popover) sits on plate black with `color-scheme: dark`. Paper never shows through behind media.

## Typography

**Display / Body Font:** Be Vietnam Pro (self-hosted 400/500/600/700, with system-ui, sans-serif)
**Mono Font:** JetBrains Mono 500 (with ui-monospace, monospace)

**Character:** One Vietnamese-first grotesque does all the talking, so diacritics render well at every size. Weight and uppercase tracking carry hierarchy, not size jumps. Mono is a tool font, reserved for machine text.

### Hierarchy
- **Display** (600, 26px, 1.2): the film title on the review source detail page only.
- **Headline** (600, 21px, 1.25, −0.01em): the page h1: project name, job name, story name.
- **Title** (600, 17px, 1.3): section h2 ("Các phần", "Video trong project"), dialog titles, the brand, tally counts, drop-zone lead text.
- **Body** (400, 15px, 1.5): the base size for text, buttons, inputs, list rows and h3/h4 (which are 600). Long prose is capped at 60 to 70ch.
- **Label** (500, 13px): form labels in Pencil, meta lines, small buttons, crumbs, table headers (600).
- **Stamp** (700, 12.5px, uppercase, 0.06em tracking): stamps and tally words. The time inside a stamp is 600 at 0.02em.
- **Serial** (500, 12.5px, tabular): "Số 0042" in Pencil.
- **Mono** (500, 12.5px, 1.55): logs, error traces, timecode inputs and hex values only.

### Named Rules
**The Tabular Rule.** Every number that can sit in a column (serials, stamp times, durations, counts, timecodes, step times) uses tabular figures.

**The Floor Rule.** Readable text is never smaller than 12.5px. Size steps are fixed: 12.5, 13, 15, 17, 21, 26px.

## Layout

The shell is a two-column grid: a resizable sticky rail (280px default, full viewport height, scrolling on its own) and the main area (padding 16px 24px, with 88px at the bottom for the sticky bar). The rail can collapse to an icon-only mini rail. At 760px and below the rail stacks above the page, and the mini rail becomes a top bar.

Pages are list-first. A page header (`page-head`) carries the h1, a meta line and, on the right, the actions with the yellow primary last ("Chạy tất cả (3)", "Chạy hàng loạt …", "Mở Phần N"). Directly under it come the state tallies when the page filters by state, then the list itself. Project-level pages (audio story, review project) use a two-column grid: a work column (minmax(0, 1fr)) holding the list and its steps, and a 360px settings column separated by a 1px rule with 20px padding, gap 28px, max width 1400px. Below 1100px the settings column follows the list, with a top rule instead.

List rows are single ruled lines: a faint rule between rows, 5 to 8px vertical padding, and a fixed grid so stamps line up row to row. Subtitle project rows run serial (64px), thumbnail and name, format (84px), duration (64px), stamp (200px), actions (150px). At phone width rows reflow into two or three grid lines, and the subtitle table turns each sentence into a ruled block.

Finished setup steps are `<details>` that fold to a one-line summary with a XONG stamp and can be reopened. Editing screens (review, layout, script) put the media stage or player beside the controls and keep it sticky; under 1100px the player moves above.

Spacing rhythm is 4, 6, 8, 12, 16 and 24px, with 10px and 14px used inside controls and section padding. Sticky action bars (`actions.sticky`) are a solid ground band with a top rule; `scroll-padding-bottom: 72px` keeps focused content above them. At phone width they become static.

## Elevation & Depth

The system is flat. Resting surfaces have no shadow and no gradient; depth comes from tone (ground, surface, field, the dark rail and plate) and from 1px rules. One shadow token exists, for layers that truly float above the page.

### Shadow Vocabulary
- **Lift** (`box-shadow: 0 18px 40px -14px color-mix(in srgb, var(--rail) 45%, transparent), 0 2px 6px -2px color-mix(in srgb, var(--ink) 20%, transparent)`): modal dialogs, the scene popover in the script editor, and the sticky "stale" bar. Nothing else.

### Named Rules
**The Only-What-Floats Rule.** A shadow means "this is above the page and will go away". Cards, rows, buttons, tallies and stamps never cast one.

## Shapes

The form language is a printed form. Corners are small: 4px for controls, fields, plates and thumbnails, 6px for dialogs, the subtitle table, drop zones, popovers and notice bars, 3px for stamps, tallies, tags and pills, and 2px for bars, tracks and markers. Rules are 1px; stamps and tallies use a 1.5px stroke. Dashed strokes mean "not yet": queued, new and waiting stamps, drop zones, the empty notebook, and the rail's add-tools. Circles are kept for status dots, swatches and the region box's remove button. The only rotation in the system is the stamp (−2°), the tally (−1.5°) and the logo mark (−2°), which is how a rubber stamp lands.

Selection inside a list or the rail is a fill plus a separate rounded marker (3px wide, inset 2px from the left, 6px from top and bottom): post yellow on the rail, ink on the playing subtitle row. It is never a border flush to the row's edge.

## Components

### Buttons
Plain and firm, like the buttons on a counter terminal.
- **Shape:** 4px corners, 1px Form Rule stroke, min height 32px (28px for small), padding 6px 12px.
- **Default:** Sheet fill with ink text. Hover darkens the stroke to Pencil and the fill to Carbon Sheet; active goes to Faint Rule. Transitions are 120ms on background, border and colour.
- **Primary:** Post Yellow fill, Letterbox Ink text at 600, stroke mixed 70% yellow into ink; hover is Worn Yellow. One per header.
- **Danger:** red text on the default button with a faint red hover. Destructive confirmations use the solid red button with Red Paper text.
- **Icon:** transparent and strokeless, 32px wide, Pencil icon; hover shows the rule stroke and ink. Icons are 24px-grid stroke SVGs from `Icon.tsx`.
- **Link:** Ledger Link text with an underline that appears on hover (3px offset).
- **Disabled:** 50% opacity, not-allowed cursor.

### Stamps (signature)
The state of every job, part, download and asset.
- **Shape:** inline label, 1.5px stroke in `currentColor`, 3px corners, padding 2px 6px 1px, rotated −2°, never wraps.
- **Type:** Stamp role (12.5px, 700, uppercase, 0.06em). The h1 stamp is 13px. Rail stamps are fixed-size beside an ellipsized name.
- **Colour by state:** running and queued in Ink Blue, awaiting review in Sealing-Wax Amber, done in Ledger Green, approved in Ledger Green with a 12% green fill, error, interrupted and cancelled in Postmark Red, new and waiting in Pencil. Queued, new and waiting use a dashed stroke.
- **Time:** " · 14:02" from the job's `state_at`, with a "27/10" prefix when not today, falling back to the time this tab saw the change.
- **Motion:** running and queued stamps pulse their ink (opacity to 0.5, 2s ease-in-out, infinite), off under `prefers-reduced-motion`.
- **Placement:** stamps sit in their own grid column or flex slot so the rotation never overlaps text.

### Serials (signature)
"Số 0042": the item's 1-based number in its list, padded to four digits, Serial role, Pencil (rail-muted on the rail). They lead sidebar job rows, project rows, audio parts, review parts, Douyin results and progress rows, and the job h1.

### Tallies
The stamped counts in a project header that double as the state filter.
- **Style:** stamp typography with the count in 17px tabular, 1.5px stroke at 55% of the state ink, rotated −1.5°, 3px corners, transparent fill.
- **State:** hover adds an 8% fill of the state ink and a full-strength stroke. The active tally is Post Yellow with an ink stroke and `aria-pressed`.

### Cards / Sections
- **Style:** a "card" is a ruled section, not a box: a 1px Form Rule above, no fill, no radius, padding 14px 0 16px. The first section under a header drops its rule.
- **Boxes:** only dialogs, the subtitle table, the file browser, media plates, the script editor's blocks, selectable cards and notices get a box (Sheet or Field fill, 1px rule, 4 to 6px corners).
- **Notices:** a tinted fill (7% info, 12% yellow, 6% red) with a 35 to 60% stroke of the same hue.

### Inputs / Fields
- **Style:** Field White fill, 1px Form Rule stroke, 4px corners, padding 6px 9px, 15px text. Labels stack above in the Label role.
- **Hover / Focus:** hover darkens the stroke to Pencil. Focus sets the stroke to ink and adds a 2px Post Yellow outline at 0 offset.
- **Disabled:** Carbon Sheet fill and Pencil text.
- **Toggles and ranges:** native controls tinted by `accent-color` (moss on paper, yellow on the rail).

### Tabs, Segments and Chips
- **Tabs:** a Sheet strip with a 1px rule and 2px inner padding; tabs are transparent with Pencil text, and the active tab is filled Post Yellow with Letterbox Ink.
- **Segments:** buttons joined in one ruled strip, separated by 1px rules; on is Post Yellow.
- **Chips:** 28px, 4px corners, Field White; on is Post Yellow.

### Navigation (the rail)
- **Style:** moss rail, 12px 8px padding, sections as 34px rows in 600 with an icon and a chevron; the project tree below with a 1px rail-rule guide line; job rows 32px with serial, ellipsized name and stamp.
- **States:** hover is rail-hover. The selected row is a 17% yellow mix with the yellow marker. The active section header only turns its text yellow. Add tools are dashed 30px buttons that fill yellow when on.
- **Foot:** the API key button and, when something is missing, a single yellow-tinted "Cần cấu hình" row that opens the key dialog.
- **Focus:** 2px yellow ring inset by 2px.
- **Mobile:** at 760px and below the rail stacks on top; the mini rail is a horizontal top bar.

### Progress
Step rows are a grid of dot, name, bar and time with faint rules between. The dot is a 10px circle: ink blue and pulsing while running, green when done, red on error. Bars are 6px tall with 2px corners on a Carbon Sheet track, ink blue while running and green when done, with a 300ms width transition.

### Dialogs
Sheet fill, 1px rule, 6px corners, 460px wide (820px for wide), Lift shadow, a rail-tinted backdrop with no blur. They open with a 160ms rise of 6px (`cubic-bezier(.16, 1, .3, 1)`), disabled under reduced motion. Actions are right-aligned above a faint top rule.

### Media Plates
Players, the region picker, thumbnails, posters and the background video sit on plate black with 4px corners. The region picker's box is a 2px Post Yellow stroke with a yellow tag and handles; extra boxes are dashed plate-info.

## Do's and Don'ts

### Do:
- **Do** show every job, part or download state as a stamp from `components/Stamp.tsx`, with its time when known.
- **Do** number every item in a list with `<Serial n>` ("Số 0042") in tabular figures.
- **Do** lead each page with its list; put shared settings in the 360px right column, and fold finished steps to one line.
- **Do** keep exactly one Post Yellow primary action per page header.
- **Do** separate sections with a 1px rule above, not a box around.
- **Do** put every video frame, thumbnail and poster on the plate (`--plate`, `color-scheme: dark`).
- **Do** use the 24px stroke icons in `Icon.tsx` for every icon.
- **Do** define new colours as tokens in `:root` and derive tints with `color-mix()`.
- **Do** turn off pulses, spins and slides under `prefers-reduced-motion`.

### Don't:
- **Don't** use Post Yellow for running, done or error states, or a state ink for selection.
- **Don't** put a shadow on anything that does not float; Lift is for dialogs, popovers and the stale bar.
- **Don't** use gradients on surfaces.
- **Don't** nest boxes: no card inside a card, no bordered fieldset inside a ruled section.
- **Don't** set readable text below 12.5px or use mono outside logs, errors, timecodes and hex values.
- **Don't** mark a selected row with a border flush to its edge; use the fill plus the detached rounded marker.
- **Don't** draw state as filled pills or coloured background badges; the stamp is the only state form.
- **Don't** use emoji or text glyphs as icons.
