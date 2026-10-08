# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python package (`uv`, `pyproject.toml`). The web interface follows the Hermes WebUI model the user
asked to start from: a standard-library Python HTTP server plus plain HTML/CSS/JS, no framework, no
bundler, no build step, launched by one command. Fonts may come from Google Fonts.

## Users

- **The author, locally.** A French-speaking developer on Windows who runs Spectre on their own
  machine to turn a free-text request into a finished, reviewed text, and wants to watch the three
  agents work instead of reading terminal output.
- **Public demo viewers.** People the author shows Spectre to (portfolio, presentation). They see a
  demo mode that runs without an API key; they never enter a key.

## Product Purpose

Spectre is a three-agent Claude writing pipeline: Scout (`claude-haiku-4-5`) turns the request into a
brief, Scribe (`claude-sonnet-5-5`) writes the full text, Warden (`claude-opus-5-5`) reviews and
returns the corrected final text. The web interface makes that pipeline usable and legible: submit a
request, follow each agent live, read the brief, draft and final text, and see tokens and cost per
agent. Success: the author prefers it to the CLI, and a viewer understands the three-agent idea at a
glance.

## Positioning

Not a chat app. One request goes through a fixed, visible chain of three specialised Claude models,
each with its own role, and the final text is the reviewed one. The interface shows the chain itself
(who is working, what each one produced, what it cost) — something a single-model chat UI cannot
truthfully show.

## Operating Context

- Launched locally with one command; binds to `127.0.0.1` only.
- Real runs need `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID` for user-scoped keys) in `.env`.
- Demo mode simulates the three agents with canned output so the UI works with no key and no network.
- A published preview page (demo mode only) is used for the public demo.

## Capabilities and Constraints

- Existing library API: `spectre.run(request)` / `build_graph(models=...)`, `SpectreResult` with
  `brief`, `draft`, `final_text`, `usage` (per agent: model, input/output tokens, cost, `truncated`).
- Server-side refusal fallbacks may make a different model answer; `usage.model` names it.
- Errors are `SpectreError` subclasses naming the agent.
- v0.1 pipeline is linear (no Warden → Scribe revision loop; planned for v0.3.0).
- No accounts, no persistence of past runs decided yet (open decision).
- Never display, log or send the API key from the UI.

## Brand Commitments

- Product name: **Spectre**. Agent names: Scout, Scribe, Warden. Interface language: French.
- The user asked for: a futuristic, modern, highly designed interface; a logo recognisable without the
  name; the word "Spectre" set in a rare, stylish typeface; effects and animations on the logo.

## Evidence on Hand

- A real run output (relativité restreinte) exists from 2026-10-07; usable as demo content.
- No users, testimonials, metrics or press exist. Do not invent any.

## Product Principles

1. Show the chain: every screen makes the Scout → Scribe → Warden order and the current agent obvious.
2. The final text is the product; process detail stays one step away from it.
3. Honest costs: tokens and dollars per agent, with the model that actually answered.
4. Works without a key in demo mode, and says clearly when it is a demo.
