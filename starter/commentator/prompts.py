"""Commentator prompts — STARTER. THIS IS YOUR MAIN BUILD.

You author the commentator's PERSONA here. This is where the lesson lives: the
difference between Challenge 2's pit-wall engineer and this broadcaster is
almost entirely in the words below.

Fill in the two TODOs:
  1. ROOT_AGENT_DESCRIPTION — one sentence describing the agent.
  2. ROOT_AGENT_INSTRUCTION — the persona / system instruction. This is the
     real work. Aim for a live TV commentator who:
       - speaks in THIRD PERSON about the whole field ("car 5 is through on
         car 6") — never "we" or "you", never a single driver's radio;
       - is short and punchy: one breath per call, ~20-35 words, lead with the
         headline;
       - NARROWS focus to the fan's selected car when the snapshot says one is
         selected (a `focus` block / a "THE FAN IS WATCHING car N" line) — open
         on that car and its battle, then widen to the field;
       - only states facts from the snapshot/tools (no invented speeds, gaps,
         names). We have POSITIONS, not time-gaps or distances — so never state a
         gap in seconds, and don't assert closeness you can't see ("right on his
         gearbox", "breathing down his neck"). Speak in order ("up to P2", "leads
         from car 94") and only call a TREND ("climbing", "just been passed") when
         a real position change backs it;
       - brings FLAVOUR — vivid verbs, a sense of stakes — but every flourish
         rides a real fact; colour decorates a fact, it never invents one;
       - is FAST: it's a live call, so narrate from the snapshot (which carries
         the leaders + the focus block) and lean away from tool calls;
       - writes for text-to-speech: digits not words, "percent" spelled out,
         names in normal case, no markdown.

Tiers: A — stand up the agent with this persona (it'll invent before the tools
are wired). C — make the persona selection-aware (the focus rules above).
D — it's read aloud by TTS, so keep the voice spoken, not written.

The reference persona is in solution/commentator/prompts.py if you get stuck —
try your own first.

The two prompt-builder functions at the bottom are GIVEN (the loop calls them);
you do not need to change them — they just wrap your persona's calls with the
authoritative snapshot.
"""
from __future__ import annotations

# ----------------------------------------------------------------------------
# TODO(student): the persona. See the module docstring for the brief.
# ----------------------------------------------------------------------------

ROOT_AGENT_DESCRIPTION = ""  # TODO(student): one sentence.

ROOT_AGENT_INSTRUCTION = """
TODO(student): write the broadcast-commentator persona here.
""".strip()


# ============================================================================
# GIVEN — proactive trigger prompt builders. The commentator loop calls these
# with the authoritative snapshot (the pinned moment) and an optional
# `watching` line (set when the fan has selected a car). You don't need to
# edit these; your persona above decides what the agent DOES with them.
# ============================================================================


def build_event_reaction_prompt(
    reason: str,
    snapshot_json: str,
    events_json: str,
    watching: str = "",
) -> str:
    watching_block = f"\n{watching}\n" if watching else ""
    return f"""LIVE COMMENTARY — EVENT CALL.

What just happened (the trigger): {reason}
{watching_block}
Authoritative snapshot at trigger time (narrate from these facts; do NOT
re-fetch the field for this call):
{snapshot_json}

Triggering events:
{events_json}

Call it now — third person, lead with the headline, 6-9 seconds spoken. If a
car is selected above, open on that car and its battle. This is LIVE — narrate
straight from the snapshot and make NO tool calls; only call a tool (one, at
most) if you must name a car that isn't in the snapshot."""


def build_lap_summary_prompt(
    lap_number: int,
    snapshot_json: str,
    watching: str = "",
) -> str:
    watching_block = f"\n{watching}\n" if watching else ""
    return f"""LIVE COMMENTARY — FIELD RECAP at lap {lap_number}.
{watching_block}
Authoritative snapshot at trigger time (narrate from these facts; do NOT
re-fetch the field for this call):
{snapshot_json}

Give the recap now: the leading order and the one or two battles worth watching.
If a car is selected above, open on where that car sits and who it's fighting.
6-9 seconds spoken. Zero tool calls unless a detail is genuinely missing."""
