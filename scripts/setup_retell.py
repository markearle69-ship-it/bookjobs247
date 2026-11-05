"""Create (or update) the four shared Retell agents: US/UK accent x female/male voice.

    python scripts/setup_retell.py --list-voices
    python scripts/setup_retell.py --us-female <id> --us-male <id> --gb-female <id> --gb-male <id>
        -> prints the four RETELL_AGENT_ID_* values to put in your env

Customers only choose "female" or "male"; you choose the actual voices here.
Per-trade questions live in /admin/trades and never need this script.

After editing app/agent_prompt.py, push the new script to all agents:

    python scripts/setup_retell.py --update

Retell's published LLM versions can't be edited, so --update creates a fresh
LLM with the new prompt, points the agent at it, and publishes the agent
(the approach proven in the original lead-router project).

Needs RETELL_API_KEY and PUBLIC_BASE_URL in the environment / .env.
"""

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent_prompt import BEGIN_MESSAGE, DYNAMIC_VARIABLES, END_CALL_TOOL, GENERAL_PROMPT, POST_CALL_ANALYSIS  # noqa: E402
from app.config import settings  # noqa: E402

API = "https://api.retellai.com"
MODEL = "gpt-4.1"


def headers():
    if not settings.retell_api_key:
        sys.exit("RETELL_API_KEY is not set")
    return {"Authorization": f"Bearer {settings.retell_api_key}"}


def call(method, path, **kw):
    resp = httpx.request(method, API + path, headers=headers(), timeout=30, **kw)
    if resp.status_code >= 400:
        sys.exit(f"{method} {path} failed: {resp.status_code} {resp.text}")
    return resp.json() if resp.content else {}


def create_llm():
    return call("POST", "/create-retell-llm", json={
        "general_prompt": GENERAL_PROMPT,
        "begin_message": BEGIN_MESSAGE,
        "model": MODEL,
        "start_speaker": "agent",
        "general_tools": [END_CALL_TOOL],
        # Fallbacks so a test call from the Retell dashboard still makes sense.
        "default_dynamic_variables": {v: "" for v in DYNAMIC_VARIABLES} | {
            "greeting": "Hi, thanks for calling Test Plumbing. Sam is out on a job right now, so I'm taking "
                        "messages. What can we help you with?",
            "answer_as": "Test Plumbing", "owner_name": "Sam", "trade": "plumber",
            "trade_questions": "- What the problem is and where in the property.",
            "emergency_signs": "Water actively leaking.", "emergency_number": "911"},
    })["llm_id"]


def agent_settings(country, gender):
    return {
        "agent_name": f"BookJobs247 {country} {gender}",
        "webhook_url": settings.url("/webhooks/retell"),
        "language": "en-GB" if country == "GB" else "en-US",
        "post_call_analysis_data": POST_CALL_ANALYSIS,
        # Caps cost per call: a message never needs more than 10 minutes.
        "max_call_duration_ms": 10 * 60 * 1000,
        "end_call_after_silence_ms": 20 * 1000,
    }


def publish(agent_id):
    resp = httpx.post(f"{API}/publish-agent/{agent_id}", headers=headers(), timeout=30)
    if resp.status_code >= 400 and "already published" not in resp.text.lower():
        sys.exit(f"publish-agent failed: {resp.status_code} {resp.text}")


def create(country, gender, voice_id):
    llm_id = create_llm()
    agent = call("POST", "/create-agent", json={
        "voice_id": voice_id,
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        **agent_settings(country, gender),
    })
    publish(agent["agent_id"])
    return agent["agent_id"]


def update(country, gender, agent_id):
    llm_id = create_llm()
    call("PATCH", f"/update-agent/{agent_id}", json={
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        **agent_settings(country, gender),
    })
    publish(agent_id)
    print(f"{country} {gender}: agent {agent_id} now uses LLM {llm_id}")


AGENTS = [("US", "female"), ("US", "male"), ("GB", "female"), ("GB", "male")]


def env_name(country, gender):
    return f"RETELL_AGENT_ID_{country}_{gender.upper()}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list-voices", action="store_true")
    for country, gender in AGENTS:
        p.add_argument(f"--{country.lower()}-{gender}")
    p.add_argument("--update", action="store_true")
    args = p.parse_args()

    if args.list_voices:
        for v in call("GET", "/list-voices"):
            print(f"{v['voice_id']:<40} {v.get('voice_name', '')}  {v.get('accent', '')} {v.get('gender', '')}")
        return

    if args.update:
        for country, gender in AGENTS:
            agent_id = getattr(settings, env_name(country, gender).lower())
            if agent_id:
                update(country, gender, agent_id)
        return

    chosen = {(c, g): getattr(args, f"{c.lower()}_{g}") for c, g in AGENTS}
    if not any(chosen.values()):
        sys.exit("Pass --us-female/--us-male/--gb-female/--gb-male voice ids (see --list-voices), or --update")
    voices = {v["voice_id"] for v in call("GET", "/list-voices")}
    for v in filter(None, chosen.values()):
        if v not in voices:
            sys.exit(f"Voice id {v!r} not found (ids are case-sensitive) - see --list-voices")
    lines = []
    for (country, gender), voice in chosen.items():
        if voice:
            lines.append(f"{env_name(country, gender)}={create(country, gender, voice)}")
    print("\nAdd these to your environment:\n")
    print("\n".join(lines))
    print("\n(A missing male voice falls back to the female agent for that country.)")


if __name__ == "__main__":
    main()
