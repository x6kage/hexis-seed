---
name: see-hear
description: Use whenever a task needs a video watched or audio heard - a YouTube video, a stream recording or clip, a render, a screen recording, a sound effect or music - instead of stepping through still frames or reading only a transcript. Claude hears nothing and sees video only as sampled stills; Gemini (Antigravity CLI on a Google AI plan) watches and listens.
---

# Watching and listening through Gemini

Adopted by the owner. The use is settled: do not ask him whether or what for.

## 1. Get the media as a local file
- A YouTube or other URL: download it first with yt-dlp, e.g.
  `python -m yt_dlp -f "bv*[height<=720]+ba/b" --merge-output-format mp4 --ffmpeg-location <ffmpeg bin dir> -o <scratchpad>/clip.%(ext)s <url>`.
  Gemini in `--mode plan` cannot fetch a URL itself (its shell tool is denied headless).
- Never send anything from a folder listed under `private_folders` in `~/.claude/local.json`.

## 2. Ask Gemini (Bash tool)
```
agy -p "Watch and listen to the video file /abs/path/clip.mp4 (do not open any other file). <the question>. Give timestamps. Answer in English. Do not edit or create any file." --model gemini-4-hydrogen-high --mode plan --print-timeout 280s 2>&1 | grep -v "logging before"
```
- `agy` is the Antigravity CLI (on Windows `~/AppData/Local/agy/bin/agy.exe`; elsewhere wherever its installer puts it).
- Model `gemini-4-hydrogen-high`: in a known-answer test it got every visual and audio event right;
  `gemini-4-argon-medium` invented a tone in a silent stretch. `agy models` lists the rest.
- `--mode plan` keeps it read-only; give the absolute path; say the answer language.
- One call took about 36 s on a 20 s clip; set the Bash timeout above `--print-timeout`.
- Ask for what the task needs: speech word for word, music and sound effects, what happens when, on-screen text.
- Long videos are untested: cut the part you need with ffmpeg (`-ss <start> -t <len>`) before sending.

## 3. Use the answer as a description, not as evidence
- Its timestamps can be off by about a second, and pitch estimates were off (1 kHz heard as about 880 Hz). Before a
  timestamp or a detail decides anything (a cut point, a bug verdict, "done"), extract that frame with ffmpeg and
  look, or measure the audio (`-af volumedetect`, a spectrum) - rules/quality.md "Evidence before code".
- If the sign-in has lapsed (`Eligibility check failed`, `not signed in`), the owner signs in again in his own
  terminal (`agy`); a session never handles his credentials.
