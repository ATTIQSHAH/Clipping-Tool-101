"""Plain-words clip edits. Run from the project folder: python tests/test_ask.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge.ai import plan_edit, rule_edit  # noqa: E402

S = {"start": 10.0, "end": 40.0, "title": "x", "layout": "pip", "template": "yellow_pop", "captions": 1, "res": 1080}
assert rule_edit("end 2 s earlier", S) == {"end": 38.0}
assert rule_edit("Start 3 seconds later and end 1.5s later", S) == {"start": 13.0, "end": 41.5}
assert rule_edit("title: He CRASHED the jet", S) == {"title": "He CRASHED the jet"}
assert rule_edit("use the split layout in 4k", S) == {"layout": "stack", "res": 2160}
assert rule_edit("no captions please", S) == {"captions": 0} and rule_edit("make it funnier", S) == {}
fake = lambda key, body: {"content": [{"type": "text", "text": 'Sure {"end": 35.5, "hack": 1}'}]}
assert plan_edit("k", "cut the boring end", S, [{"w": "hi", "start": 11.0}], ["yellow_pop"], post=fake) == {"end": 35.5}
print("ok")
