---
name: hexis-research
description: Use before choosing or configuring any tool, library, runtime, model, vendor or setting - editing package.json, tsconfig, biome.json, bunfig.toml, vercel.json, pyproject or ruff or pyright config, Cargo.toml, or installing a package - fetch the current primary source first, never configure from memory.
---

# Current information first

Full text: `~/.claude/rules/research.md`.

## Before the edit or the install
1. **Fetch the current primary source in this turn**: the tool's own docs, its configuration reference, the release notes of the installed version, the vendor's terms. A docs-lookup agent (Sonnet, medium) is the cheap way; skipping the fetch is never fine.
2. **Probe the machine**: the installed version (`<tool> --version`, `winget list`, `pip show`, lockfiles) - configure for that version, and pin schemas and versions to it.
3. **Name the alternatives**, including ones not in use, and say which you actually checked. A question about which tool to use is a question about today.
4. **Cite** what you relied on: URL and the date the page shows; keep it apart from what you remember.

## While configuring
- Follow the tool's documented setup for the ecosystem in use (for example Bun + Biome: exact-pinned devDependency, the `$schema` of the installed version, the documented tsconfig template), not a pattern recalled from an older version.
- Defaults change between majors (Biome 2 replaced `ignore`/`include` with `includes`, moved organize-imports to `assist`): read the upgrade guide when the installed major differs from what you know.
- An unverifiable claim is labelled as such, never stated as fact.

## Why this is pushed here
The rule is always loaded and is still skipped: tool configs get set up and vendor terms get answered from memory. The push puts it in front of the model at the moment of the edit.
