"""Word-level captions -> ASS (styles, active-word highlight, hook effects, emojis, censoring)."""
import re

SENT = (".", "?", "!")

EMOJI_TRIGGERS = {
    ("fire", "lit", "hot", "cook", "insane", "burn"): "🔥",
    ("dead", "die", "died", "kill", "killed", "rip", "skull", "wasted"): "💀",
    ("cops", "police", "busted", "siren", "stars"): "🚨",
    ("money", "rich", "cash", "paid", "bag", "dollar", "crypto"): "💰",
    ("no way", "omg", "what", "shocked", "screaming", "crazy", "bruh", "wait"): "😱",
    ("win", "won", "clutch", "champion", "gg", "first"): "🏆",
    ("explode", "crashed", "boom", "bang", "glitch", "crash"): "💥",
    ("look", "see", "watch", "peep", "eyes"): "👀",
    ("fast", "speed", "run", "lightning"): "⚡",
    ("goat", "king", "queen", "best"): "👑",
    ("game", "gaming", "play", "player"): "🎮",
    ("headshot", "aim", "target", "shot"): "🎯"
}

PROFANITIES = {
    "fuck", "fucking", "fucked", "fucker", "shit", "shitting", "bitch", "bitches",
    "asshole", "dick", "pussy", "bastard", "cunt", "nigger", "nigga"
}


def censor_word(w):
    clean = re.sub(r"[^\w]", "", w.lower())
    if clean in PROFANITIES:
        punct = "".join(c for c in w if not c.isalnum())
        return "*" * len(clean) + punct
    return w


def get_emoji_for_phrase(words):
    text = " ".join(w["w"].lower() for w in words)
    for triggers, emoji in EMOJI_TRIGGERS.items():
        for trg in triggers:
            if re.search(r"\b" + re.escape(trg) + r"\b", text):
                return emoji
    return ""


def _bgr(hexcol, alpha=0):
    h = hexcol.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# mode: "phrase" (2-4 words on screen, spoken word highlighted) or "word" (one word at a time)
# mv: distance of the text from the bottom edge (px on a 1920-high canvas); scale_active: grow the spoken word (%)
# glow: soft glow around letters; box: dark box behind the text
TEMPLATES = {
    "yellow_pop": dict(font="Arial", size=86, bold=1, primary="#FFFFFF", active="#FFE600", outline="#000000", ow=7,
                       shadow=2, box=False, upper=True, pop=True, mode="phrase", mv=470, scale_active=0, glow=0),
    "bold_white": dict(font="Arial", size=86, bold=1, primary="#FFFFFF", active="#FFFFFF", outline="#000000", ow=7,
                       shadow=2, box=False, upper=True, pop=True, mode="phrase", mv=470, scale_active=0, glow=0),
    "karaoke_green": dict(font="Arial", size=84, bold=1, primary="#FFFFFF", active="#39FF88", outline="#0B2A18", ow=8,
                          shadow=2, box=False, upper=True, pop=False, mode="phrase", mv=470, scale_active=0, glow=0),
    "hype_scale": dict(font="Arial", size=80, bold=1, primary="#FFFFFF", active="#FF3B5C", outline="#000000", ow=7,
                       shadow=3, box=False, upper=True, pop=False, mode="phrase", mv=700, scale_active=125, glow=0),
    "neon": dict(font="Arial", size=84, bold=1, primary="#FFFFFF", active="#00E5FF", outline="#0077FF", ow=6,
                 shadow=0, box=False, upper=True, pop=True, mode="phrase", mv=520, scale_active=0, glow=1),
    "boxed": dict(font="Arial", size=76, bold=1, primary="#FFFFFF", active="#FFD400", outline="#000000", ow=14,
                  shadow=0, box=True, upper=False, pop=False, mode="phrase", mv=470, scale_active=0, glow=0),
    "one_word": dict(font="Arial", size=150, bold=1, primary="#FFFFFF", active="#FFE600", outline="#000000", ow=10,
                     shadow=3, box=False, upper=True, pop=True, mode="word", mv=650, scale_active=0, glow=0),
    "minimal": dict(font="Arial", size=62, bold=0, primary="#FFFFFF", active="#FFFFFF", outline="#000000", ow=4,
                    shadow=1, box=False, upper=False, pop=False, mode="phrase", mv=300, scale_active=0, glow=0),
}


def build_cues(words, max_words=3, max_chars=22, gap=0.35):
    """Group words into short cues. words: [{'w','start','end'}] on the clip timeline."""
    groups, cur = [], []
    for w in words:
        if cur:
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if (len(cur) >= max_words or chars > max_chars or w["start"] - cur[-1]["end"] > gap
                    or cur[-1]["w"].endswith(SENT + (",",))):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    cues = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1][0]["start"] if i + 1 < len(groups) else 1e9
        prev_end = cues[-1]["end"] if cues else 0.0
        start = max(g[0]["start"] - 0.03, prev_end)
        end = min(g[-1]["end"] + 0.12, nxt)
        end = max(end, min(start + 0.35, nxt))          # min on-screen time
        end = min(end, max(start + 2.0, g[-1]["end"]))  # max on-screen time
        cues.append({"start": start, "end": end, "words": g})
    return cues


def _ts(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(s):
    return s.replace("{", "(").replace("}", ")").replace("\\", "")


def to_ass(cues, template="yellow_pop", width=1080, height=1920, censor=False, emojis=True, hook_boost=True,
           banner_text="", banner_style="white_box", banner_x=0.5, banner_y=0.12):
    t = TEMPLATES.get(template) or TEMPLATES["yellow_pop"]
    style_box = 3 if t["box"] else 1
    back = _bgr("#000000", 90 if t["box"] else 128)
    outc = _bgr(t["outline"], 90) if t["box"] else _bgr(t["outline"])

    # Scale font size, margins, and outline with export resolution / aspect ratio
    scale = float(height) / 1920.0
    fsize = max(24, int(round(t["size"] * scale)))
    mv = max(28, int(round(t["mv"] * scale)))
    ow = max(2, int(round(t["ow"] * scale)))
    sh = max(1, int(round(t["shadow"] * scale)))
    bsize = max(22, int(round(52 * scale)))
    bmv = max(20, int(round(110 * scale)))
    
    # Banner styles for top hook headline
    if banner_style == "dark_box":
        banner_def = f"Style: Banner,Arial,{bsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,16,6,8,80,80,{bmv},1\n"
    elif banner_style == "neon":
        banner_def = f"Style: Banner,Arial,{bsize+2},&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,10,8,80,80,{bmv},1\n"
    else:  # white_box (standard TikTok / Instagram card)
        banner_def = f"Style: Banner,Arial,{bsize},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,16,6,8,80,80,{bmv},1\n"

    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
        "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,"
        "MarginR,MarginV,Encoding\n"
        f"Style: Main,{t['font']},{fsize},{_bgr(t['primary'])},{_bgr(t['primary'])},{outc},{back},"
        f"{-1 if t['bold'] else 0},0,0,0,100,100,0,0,{style_box},{ow},{sh},2,60,60,{mv},1\n"
        + (banner_def if banner_text and banner_style != "none" else "") +
        "\n[Events]\nFormat: Layer,Start,End,Name,Style,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    glow = r"{\blur5}" if t["glow"] else ""
    sa = t["scale_active"]
    lines = []
    if banner_text and banner_style != "none":
        clean_banner = _esc(banner_text).strip()
        bx = int(width * max(0.05, min(0.95, float(banner_x if banner_x is not None else 0.5))))
        by = int(height * max(0.05, min(0.95, float(banner_y if banner_y is not None else 0.12))))
        lines.append(f"Dialogue: 1,0:00:00.00,9:59:59.00,Banner,,0,0,0,,{{\\an5\\pos({bx},{by})}}{clean_banner}")
    for cue in cues:
        raw_words = cue["words"]
        processed_words = []
        for w in raw_words:
            word_txt = censor_word(w["w"]) if censor else w["w"]
            clean_txt = _esc(word_txt).upper() if t["upper"] else _esc(word_txt)
            processed_words.append(clean_txt)
        
        # Check for contextual emoji
        phrase_emoji = get_emoji_for_phrase(raw_words) if emojis else ""
        if phrase_emoji and processed_words:
            processed_words[-1] = f"{processed_words[-1]} {phrase_emoji}"
            
        for i, w in enumerate(raw_words):
            s = cue["start"] if i == 0 else w["start"]
            e = raw_words[i + 1]["start"] if i + 1 < len(processed_words) else cue["end"]
            
            # Attention grabber for first 3-6s: extra pop + bounce
            is_hook = hook_boost and s < 4.5
            if is_hook:
                pop = r"{\fscx112\fscy112\t(0,100,\fscx100\fscy100)}"
            else:
                pop = r"{\fscx82\fscy82\t(0,90,\fscx100\fscy100)}" if t["pop"] else ""
                
            if t["mode"] == "word":
                body = processed_words[i]
            else:
                parts = []
                for j, txt in enumerate(processed_words):
                    on = j == i
                    act_col = "#FF3366" if (is_hook and on and t["active"] == "#FFFFFF") else (t["active"] if on else t["primary"])
                    tag = f"\\c{_bgr(act_col)}"
                    cur_scale = sa if on else 100
                    if is_hook and on:
                        cur_scale = max(cur_scale, 115)
                    if cur_scale != 100:
                        tag += f"\\fscx{cur_scale}\\fscy{cur_scale}"
                    parts.append(f"{{{tag}}}{txt}")
                body = " ".join(parts)
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},,Main,0,0,0,,{glow}{pop if (i == 0 or t['mode'] == 'word' or is_hook) else ''}{body}")
    return head + "\n".join(lines) + "\n"
