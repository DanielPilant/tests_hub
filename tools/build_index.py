"""Embed the quiz JSON files into index.html (run: py -3 tools/build_index.py)."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
QUIZ_FILES = [
    "functional_python_quiz_20_he.json",
    "programming_language_principles_quiz_20_he.json",
    "programming_language_principles_set2_quiz_20_he.json",
]
quizzes = [json.loads((root / name).read_text(encoding="utf-8")) for name in QUIZ_FILES]
ids = [q["quiz_id"] for q in quizzes]
assert len(set(ids)) == len(ids), "duplicate quiz_id"
question_ids = [question["id"] for q in quizzes for question in q["questions"]]
assert len(set(question_ids)) == len(question_ids), "question id collides across quizzes"
payload = json.dumps({"quizzes": quizzes}, ensure_ascii=False, separators=(",", ":"))
# Escape characters that could end the <script> element or confuse HTML parsing.
for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
    payload = payload.replace(ch, esc)
assert "</script" not in payload.lower()
template = (root / "tools" / "index.template.html").read_text(encoding="utf-8")
assert template.count("/*__QUIZ_DATA__*/") == 1
(root / "index.html").write_text(template.replace("/*__QUIZ_DATA__*/", payload), encoding="utf-8", newline="\n")
for q in quizzes:
    print(f"embedded {q['quiz_id']} v{q['content_version']} ({len(q['questions'])} questions)")
