"""Optional smarter scoring with Claude. The transcript of each candidate clip is sent to the Anthropic API.
Without an API key the app uses its built-in scoring. Any failure here is non-fatal."""
import json, os, re, urllib.request

MODEL = os.environ.get("CLIPFORGE_AI_MODEL", "claude-haiku-5-5")
URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "You are an editor who picks short-form clips (TikTok, Reels, Shorts) from streams and videos. "
    "You only see transcripts. Judge ONLY what the transcript supports and never invent dialogue or events. "
    "Reply with JSON only, no prose and no code fences."
)

PROMPT = """For each candidate clip below, return one JSON object with these keys:
id (copy it), humor, surprise, story, hype (each 0-10, how strongly the transcript shows it),
complete (true if the clip has its setup AND its payoff or reaction; false if it starts or ends mid-thought),
title (max 8 words, written by you as a hook, NOT a quote of the transcript),
reason (one short sentence on why it would or would not work as a clip).
Return a JSON array, one object per clip.

Clips:
{clips}"""


def _post(api_key, body, timeout=60):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def parse(text):
    """Pull the JSON array out of a model reply (tolerates code fences or a little extra text)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        raise ValueError("no JSON array in reply")
    out = {}
    for o in json.loads(text[a:b + 1]):
        try:
            hi = max(float(o.get("humor", 0)), float(o.get("surprise", 0)), float(o.get("hype", 0)), float(o.get("story", 0)))
            avg = (float(o.get("humor", 0)) + float(o.get("surprise", 0)) + float(o.get("story", 0)) + float(o.get("hype", 0))) / 4
            score = min(1.0, (0.6 * hi + 0.4 * avg) / 10)
            if o.get("complete") is False:
                score *= 0.75
            out[str(o["id"])] = {"score": round(score, 3), "complete": bool(o.get("complete", True)),
                                 "title": str(o.get("title", ""))[:90], "reason": str(o.get("reason", ""))[:220],
                                 "humor": o.get("humor"), "surprise": o.get("surprise")}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def score_clips(api_key, items, log=print, post=_post):
    """items: [{'id': str, 'text': str}]. Returns {id: {...}} (may be partial). Never raises."""
    results = {}
    for i in range(0, len(items), 20):
        batch = items[i:i + 20]
        listing = "\n\n".join(f"[id={c['id']}]\n{c['text'][:1400]}" for c in batch)
        try:
            resp = post(api_key, {"model": MODEL, "max_tokens": 3000, "system": SYSTEM,
                                  "messages": [{"role": "user", "content": PROMPT.format(clips=listing)}]})
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            results.update(parse(text))
        except Exception as e:  # network, bad key, bad reply: fall back to built-in scoring
            log(f"AI scoring skipped for one batch ({str(e)[:120]})")
    return results


def test_key(api_key, post=_post):
    resp = post(api_key, {"model": MODEL, "max_tokens": 5, "messages": [{"role": "user", "content": "Say ok"}]}, timeout=30)
    return bool(resp.get("content"))


# ---------------- edit a clip in plain words ----------------
EDIT_KEYS = ("start", "end", "title", "layout", "template", "captions", "res")
EDIT_PROMPT = """You change one short video clip as the user asks. Current clip (times in seconds of the source video):
{state}
Words spoken around the clip (time: word):
{words}
Allowed changes: start, end (numbers), title (max 8 words), layout (pip = facecam over gameplay, stack = facecam
above gameplay, follow = follow the face, crop = center, blur = blurred fit), template (one of {templates}),
captions (1 or 0), res (1080, 1440, 2160). Prefer cutting at word boundaries.
User request: {ask}
Reply with a JSON object holding ONLY the fields to change, e.g. {{"end": 41.2}}. Reply {{}} if the request can't be done."""


def plan_edit(api_key, ask, state, words, templates, post=_post):
    """Ask the model for a clip patch. Returns a dict with only EDIT_KEYS. Raises on network or reply errors."""
    near = " ".join(f"{w['start']:.1f}:{w['w']}" for w in words)[:6000]
    resp = post(api_key, {"model": MODEL, "max_tokens": 300, "system": "Reply with JSON only, no prose and no code fences.",
                          "messages": [{"role": "user", "content": EDIT_PROMPT.format(
                              state=json.dumps(state), words=near, templates=", ".join(templates), ask=ask[:500])}]})
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    a, b = text.find("{"), text.rfind("}")
    o = json.loads(text[a:b + 1]) if 0 <= a < b else {}
    return {k: v for k, v in o.items() if k in EDIT_KEYS}


_NUM = r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)?"
LAYOUT_WORDS = (("facecam over", "pip"), ("pip", "pip"), ("split", "stack"), ("stack", "stack"), ("follow", "follow"),
                ("center", "crop"), ("centre", "crop"), ("blur", "blur"))


def rule_edit(ask, state):
    """Common requests without an AI key: 'end 2 s earlier', 'start 3 seconds later', 'title: X', 'split layout',
    'no captions', '4k'. Returns a patch dict (empty if nothing was understood)."""
    a, out = ask.lower().strip(), {}
    for m in re.finditer(r"\b(start|begin|end|finish|stop)\w*\s+" + _NUM + r"\s+(earlier|sooner|before|later|after)", a):
        key = "start" if m.group(1) in ("start", "begin") else "end"
        d = float(m.group(2)) * (-1 if m.group(3) in ("earlier", "sooner", "before") else 1)
        out[key] = round(state[key] + d, 3)
    m = re.search(r"\b(?:title|hook)\b\s*(?:to|:|=|is)\s*(.+)", ask, re.I)
    if m:
        out["title"] = m.group(1).strip().strip("\"'")[:90]
    if "title" not in out:
        for w, lay in LAYOUT_WORDS:
            if w in a:
                out["layout"] = lay
                break
    if re.search(r"\b(no|without|remove|hide|off)\b.*\bcaptions?\b|\bcaptions?\b.*\boff\b", a):
        out["captions"] = 0
    elif re.search(r"\b(add|show|on|with)\b.*\bcaptions?\b", a):
        out["captions"] = 1
    for w, r in (("4k", 2160), ("2k", 1440), ("1440", 1440), ("1080", 1080)):
        if re.search(r"\b" + w + r"\b", a):
            out["res"] = r
            break
    return out
