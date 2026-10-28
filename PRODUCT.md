# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The owner and a small team of Vietnamese content creators who share one self-hosted instance (locally on 127.0.0.1:8020, or through a Cloudflare Tunnel link with a shared password). They are operators, not first-time visitors: they know the workflow and want throughput.

## Product Purpose

Auto-Sub turns foreign and raw material into Vietnamese videos ready to publish:

- **Làm phụ đề video**: Chinese/English videos get the old burnt-in subtitles covered, Vietnamese subtitles and a Vietnamese voice-over (keeping music and effects).
- **Tải video Douyin**: pull videos from Douyin channels into projects.
- **Review phim**: write and voice a review script over a film, then lay out cover, subtitles and title.
- **Truyện Audio**: turn script files (.txt/.docx/.srt) into narrated videos over a looped background video with music.

Success means many videos finished per day with little hand-holding: queue a batch, watch progress, check results, download.

## Positioning

A private, self-hosted production line that runs the whole chain (separation, ASR, LLM translation, TTS, mixing, rendering) on the team's own machine, organised by project (one channel or one story per project) with shared presets.

## Operating Context

- Main rhythm is batch work: drop many videos or scripts in, let the queue run (one subtitle job at a time; two audio-story parts at a time), then monitor progress and review or download results. Fine hand-editing (subtitle region, script blocks, layout) happens but is secondary.
- Used mainly on large desktop/laptop screens for long sessions; phones only occasionally check progress.
- Jobs take minutes to hours; the UI is left open in a tab and must show state at a glance.

## Capabilities and Constraints

- Frontend: React 18 + TypeScript + Vite in `frontend/`, single global stylesheet `frontend/src/styles.css`, no UI library, no new npm dependencies without reason.
- All user-facing copy is Vietnamese; Vietnamese diacritics must render well at every size.
- The app can be reached through a Cloudflare Tunnel (100 MB request cap, ~100 s timeout); uploads are chunked.
- Backend events stream over one shared SSE connection.

## Brand Commitments

- Name: Auto-Sub. Voice: plain, direct Vietnamese, short labels.
- Subtitle fonts in `fonts/` (Be Vietnam Pro, Lexend, Montserrat, Oswald, Roboto, etc.) are render assets for videos, not UI branding.

## Evidence on Hand

No marketing, testimonials or metrics exist; none should be invented.

## Product Principles

1. State at a glance: what is running, waiting, done or broken must be readable without opening anything.
2. Throughput over ceremony: batch actions first, few clicks per video.
3. The video is the subject: chrome stays quiet so frames, subtitles and covers are judged accurately.
4. Never lose work: long uploads and jobs survive navigation, errors say what to do next.
