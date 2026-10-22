"""Validate a quiz JSON file: structure, answer keys, Python checks and C++ cases.

Usage: py -3 -I tools/validate_quiz.py <quiz.json> [--no-cpp]

Python checks:
  * functional_python schema: question code runs first when run_question_code_first is true.
  * other schemas: python_assertions are self-contained models; question code is never run.
C++ cases are compiled with g++ inside WSL (g++ -std=c++17 -Wall -Wextra -pedantic-errors).
A case with expect_compile=false passes only when compilation fails; such code is never run.
link_cases compile every source to its own object file first, then check the link result
against expect_link (a link failure is not a compile failure).
"""
import json
import subprocess
import sys
from collections import Counter

CXX = ["wsl", "-d", "Ubuntu", "--exec", "bash", "-c"]
CXX_SCRIPT = (
    'd=$(mktemp -d) && cat > "$d/t.cpp" && '
    'if g++ -std=c++17 -Wall -Wextra -pedantic-errors "$d/t.cpp" -o "$d/t" 2>"$d/err"; then '
    '  echo COMPILED; if [ "$RUN" = 1 ]; then "$d/t"; echo "EXIT=$?"; fi; '
    'else echo COMPILE_FAILED; head -c 300 "$d/err" | tr "\\n" " "; fi; rm -rf "$d"'
)


def cxx_version():
    out = subprocess.run(CXX + ["g++ --version | head -1"], capture_output=True, text=True)
    return out.stdout.strip()


def run_cpp(case):
    script = ("RUN=1; " if case.get("run_if_compiled") else "RUN=0; ") + CXX_SCRIPT
    out = subprocess.run(CXX + [script], input=case["source"], capture_output=True, text=True, encoding="utf-8")
    text = out.stdout
    compiled = text.startswith("COMPILED")
    if compiled != case["expect_compile"]:
        return False, f"compile={'ok' if compiled else 'failed'} expected={'ok' if case['expect_compile'] else 'failure'} {text[:300]}"
    if compiled and case.get("run_if_compiled"):
        code = int(text.rsplit("EXIT=", 1)[1].split()[0])
        if code != case.get("expected_exit_code", 0):
            return False, f"exit={code} expected={case.get('expected_exit_code')}"
        return True, f"compiled, ran, exit {code}"
    return True, "compiled" if compiled else "expected compile failure: " + text[len("COMPILE_FAILED"):].strip()[:120]


def run_link(case):
    """Compile each source to its own object file, then link; checks compile and link status separately."""
    import base64
    import re
    files = case["sources"]
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+\.cpp", name) for name in files), "unsafe file name"
    writes = "; ".join(
        f'echo {base64.b64encode(src.encode()).decode()} | base64 -d > "$d/{name}"' for name, src in files.items())
    objs = " ".join(f'"$d/{name}.o"' for name in files)
    compiles = "; ".join(
        f'(g++ -std=c++17 -Wall -Wextra -pedantic-errors -c "$d/{name}" -o "$d/{name}.o" 2>>"$d/cerr" && echo OBJ_OK:{name}) || echo OBJ_FAIL:{name}'
        for name in files)
    run = 'RUN=1; ' if case.get("run_if_linked") else 'RUN=0; '
    script = (run + 'd=$(mktemp -d); ' + writes + '; ' + compiles + '; '
              f'if g++ {objs} -o "$d/prog" 2>"$d/lerr"; then echo LINKED; '
              'if [ "$RUN" = 1 ]; then "$d/prog"; echo "EXIT=$?"; fi; '
              'else echo LINK_FAILED; head -c 400 "$d/lerr" | tr "\\n" " "; fi; rm -rf "$d"')
    text = subprocess.run(CXX + [script], capture_output=True, text=True, encoding="utf-8").stdout
    failed_objs = re.findall(r"OBJ_FAIL:(\S+)", text)
    if case.get("expect_object_compilation", True) and failed_objs:
        return False, f"object compilation failed: {failed_objs}"
    linked = "\nLINKED" in "\n" + text
    if linked != case["expect_link"]:
        return False, f"link={'ok' if linked else 'failed'} expected={'ok' if case['expect_link'] else 'failure'} {text[-300:]}"
    if linked and case.get("run_if_linked"):
        code = int(text.rsplit("EXIT=", 1)[1].split()[0])
        if code != case.get("expected_exit_code", 0):
            return False, f"exit={code} expected={case.get('expected_exit_code')}"
        return True, f"all objects compiled, linked, ran, exit {code}"
    if linked:
        return True, "all objects compiled, linked"
    reason = text.split("LINK_FAILED", 1)[1].strip()
    return True, "all objects compiled; expected link failure: " + reason[reason.find("undefined"):][:110]


def main():
    path = sys.argv[1]
    use_cpp = "--no-cpp" not in sys.argv
    data = json.load(open(path, encoding="utf-8"))
    qs = data["questions"]
    ids = [q["id"] for q in qs]
    assert len(qs) == 20 == data["question_count"], len(qs)
    assert len(set(ids)) == 20, "duplicate ids"
    print(data["quiz_id"], "content_version", data["content_version"])
    if use_cpp:
        print("C++:", cxx_version())
    print("Python:", sys.version.split()[0])
    failures = 0
    py_checks = cpp_cases = cpp_expected_fail = link_cases = link_expected_fail = 0
    for q in qs:
        problems = []
        opt_ids = [o["id"] for o in q["options"]]
        if opt_ids != ["A", "B", "C", "D"]:
            problems.append(f"option ids {opt_ids}")
        if len({(o["text"], o["code"]) for o in q["options"]}) != 4:
            problems.append("duplicate options")
        if any(not (o["text"] or o["code"]) for o in q["options"]):
            problems.append("empty option")
        if q["answer"]["correct_option_id"] not in opt_ids:
            problems.append("bad key")
        if set(q["answer"]["option_feedback"]) != set(opt_ids):
            problems.append("feedback keys")
        av = q["author_validation"]
        notes = []
        if av.get("python_assertions"):
            ns = {}
            try:
                if av.get("run_question_code_first"):
                    exec(q["code_blocks"][0]["code"], ns)
                exec(av["python_assertions"], ns)
                py_checks += 1
                notes.append("python ok")
            except Exception as e:  # noqa: BLE001
                problems.append(f"python: {e!r}")
        for case in av.get("cpp_cases") or []:
            cpp_cases += 1
            cpp_expected_fail += not case["expect_compile"]
            if not use_cpp:
                continue
            ok, msg = run_cpp(case)
            notes.append(f"cpp[{case['label']}]: {msg}")
            if not ok:
                problems.append(f"cpp[{case['label']}]: {msg}")
        for case in av.get("link_cases") or []:
            link_cases += 1
            link_expected_fail += not case["expect_link"]
            if not use_cpp:
                continue
            ok, msg = run_link(case)
            notes.append(f"link[{case['label']}]: {msg}")
            if not ok:
                problems.append(f"link[{case['label']}]: {msg}")
        status = "FAIL" if problems else "OK"
        failures += bool(problems)
        print(f"{q['id']} {status} key={q['answer']['correct_option_id']} | " + "; ".join(problems or notes))
    print(f"python model checks: {py_checks}; cpp cases: {cpp_cases} (expected compile failures: {cpp_expected_fail}); "
          f"link cases: {link_cases} (expected link failures: {link_expected_fail})")
    print("answer distribution:", dict(sorted(Counter(q["answer"]["correct_option_id"] for q in qs).items())))
    print(f"{20 - failures}/20 questions passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
