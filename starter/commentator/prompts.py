"""Commentator prompts — STARTER. THIS IS YOUR MAIN BUILD.

You author the commentator's PERSONA here. This is where the lesson lives: the
difference between Challenge 2's pit-wall engineer and this broadcaster is almost
entirely in the words below.

The commentator is a CONTINUOUS play-by-play caller. It is driven by a loop that,
every beat, hands it: the last few lines it said, the ranked ACTION since then
(the deterministic scorer is the "director"), and the current FIELD. Your persona
decides how it turns that into the next 2-3 sentences of flowing commentary.

Fill in the two TODOs:
  1. ROOT_AGENT_DESCRIPTION — one sentence describing the agent.
  2. ROOT_AGENT_INSTRUCTION — the persona / system instruction. Aim for a live TV
     commentator who:
       - calls the race as a CONTINUOUS STREAM: each turn CONTINUES from the last
         lines it said (it's shown them) and never repeats them — so it flows;
       - speaks third person ("car 5 is through on car 6"), never "we"/"you";
       - LEADS with the front of the race (the lead battle, top 5), dropping down
         the order for a notable move, then back to the front;
       - NARROWS onto the fan's selected car when one is set (it's told so) — that
         car becomes the main story, while still glancing at the front;
       - in QUIET spells keeps talking — running order, an Attack Mode/energy
         picture, a storyline — without just repeating the order it gave last time;
       - only states facts from the data (no invented speeds, gaps, names); we have
         POSITIONS not time-gaps, so no seconds and no "on his gearbox" closeness;
       - brings flavour (vivid verbs, stakes) but every flourish rides a real fact;
       - writes for the screen (and optional voice): digits, "percent" spelled out,
         names in normal case, no markdown.

Tiers: A — stand up the agent with this persona. C — make it selection-aware (the
focus rules above). D — it can be read aloud by TTS, so keep the voice speakable.

The reference persona is in solution/commentator/prompts.py if you get stuck — try
your own first.

The build_commentary_prompt function below is GIVEN (the loop calls it each beat);
you don't need to change it — it just wraps your persona's call with the recent
lines, the ranked action, and the live field.
"""
from __future__ import annotations

# ----------------------------------------------------------------------------
# TODO(student): the persona. See the module docstring for the brief.
# ----------------------------------------------------------------------------

ROOT_AGENT_DESCRIPTION = ""  # TODO(student): one sentence.

ROOT_AGENT_INSTRUCTION = """
TODO(student): write the continuous play-by-play commentator persona here.
""".strip()


# ============================================================================
# GIVEN — the continuous-commentary prompt. The loop calls this every beat with
# the lines the commentator just said (for continuity / no-repeat), the ranked
# action since the last beat (the scorer's "director" output), the live field
# snapshot, and the `watching` selection line. You don't edit this; your persona
# above decides what the agent DOES with it.
# ============================================================================


def build_commentary_prompt(
    recent_lines: str,
    action_json: str,
    snapshot_json: str,
    watching: str = "",
) -> str:
    watching_block = f"\n{watching}\n" if watching else ""
    recent_block = recent_lines.strip() or "(this is your opening line — set the scene.)"
    return f"""LIVE COMMENTARY — continue the call.
{watching_block}
You have just said (oldest first; CONTINUE from here, do NOT repeat these lines):
{recent_block}

Most significant action since your last line (ranked; empty list = a quiet spell):
{action_json}

Current field right now (authoritative — narrate only from this):
{snapshot_json}

Give your next 2-3 sentences of flowing commentary now. Lead with the front of
the race — or the selected car if one is set above — call any new action, and
build on your last line without repeating it. No tool calls."""
