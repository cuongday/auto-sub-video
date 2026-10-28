---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/styles.css"]
---

# Surface: Auto-Sub app shell and working screens

Scope: the whole web app in frontend/ (sidebar, project/story pages, job progress, editing screens). Mode: Operate.
Audience: owner + small team of Vietnamese creators, batch production on large desktop screens, long sessions.
Avoid (user): clutter/decoration, small hard-to-read text, sparse layouts that force scrolling.

## Direction contract

THESIS: A post-office counter for videos: every job is a numbered item that gets stamped as it moves. Refuses the category default of a grey dashboard with one neon accent and pills.

OWN-WORLD: Bưu điện Sài Gòn. Deep moss-green rail (#1F3A2E family) carrying navigation; warm form-paper ground (light, slightly green-tinted, never cream-beige); ink near-black text; post yellow (#F2C230 family) for the primary action and selection; postmark red for error/cancel; ok green for done. Square-ish 4px corners, 1px ruled hairlines like form fields, no shadows, no gradients. Be Vietnam Pro for UI at 15px base; tabular numerals for counts, times and serials.

STORY: The operator sees at a glance what is queued, running, done or broken across all projects, starts batches in one click, and opens one item only when it needs a hand.

FIRST VIEWPORT: Left: green rail with sections (Làm phụ đề video, Truyện Audio, Tải video Douyin, Review phim), project tree with serials and state stamps, API key at foot. Right: project page header (name, counts as stamped tallies, primary yellow "Chạy tất cả"), then dense item list rows: serial No. 0042, name, kind, duration, stamp, actions. Video frames sit on a dark plate.

FORM: Grounded list #6 (Bưu điện counter), assigned by roll. seed:81c8cb657262052f

SIGNATURE: State is a postmark stamp — an outlined, slightly rotated (−2°) uppercase rubber-stamp label with the state's colour and the time it changed (ĐANG CHẠY · 14:02); running stamps pulse their ink softly; every item carries a serial number (Số 0042) in tabular figures.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
