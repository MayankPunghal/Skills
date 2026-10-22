"""Find the "missing" reference DLLs in a shared library checkout that was reorganised, and stage them under the paths the repositories expect.

    python <skill>/scripts/stage_library.py --library <path to the shared Library checkout> [--out <stage folder>] [--apply]

Reads the static build check (assessment/build/index.json: "reference DLL not found (X.dll expected at Library/old/X.dll)"), looks for each file
BY NAME in the library checkout, and prints where it is now. Without --apply it only reports. With --apply it builds a staging folder that acts
as the group folder next to the repositories: a junction (or symlink) per top-level library folder, plus copies of the files under their old
paths (the library checkout itself is never changed), writes aliases.json there and sets assessment.json -> library_stage. build_check.py then
finds the files and says in the prerequisites which old path was pointed at which current folder.

Honest limits: a file found only by its name may be a different version of the DLL; the build result with the stage tells whether the code
compiles against it, not that it is the version production uses. A file found nowhere is truly missing and stays a question for the client.
"""
import argparse
import json
import os
import re
import shutil
import subprocess

from _common import OUT, load_config, read_json, save_config, utf8_stdout, write_json


def link(src, dst):
    if os.path.exists(dst):
        return
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", dst, src], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.symlink(src, dst, target_is_directory=True)
    if not os.path.exists(dst):  # no junction rights: copy instead
        shutil.copytree(src, dst)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True, help="the shared library checkout (for example the Library repository)")
    ap.add_argument("--out", help="staging folder (default: <workspace>/assessment/build/library-stage)")
    ap.add_argument("--prefer", help="when a file exists in several framework folders, prefer paths containing this text (for example net472 for .NET Framework solutions)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    idx = read_json(os.path.join(OUT, "build", "index.json"))
    if not idx:
        raise SystemExit("run build_check.py (static) first")
    lib = os.path.abspath(a.library)
    by_name = {}
    for dp, dn, fn in os.walk(lib):
        dn[:] = [d for d in dn if d not in (".git", "obj")]
        for f in fn:
            by_name.setdefault(f.lower(), []).append(os.path.relpath(os.path.join(dp, f), lib).replace("\\", "/"))
    need = {}
    for s in idx["solutions"]:
        for i in s["static"]["issues"]:
            m = re.search(r"\((.+?) expected at (.+?)\)", i)
            if m:
                need.setdefault(m.group(2), set()).add(s["id"].split("/")[0])
    found, lost = {}, []
    for exp, repos in sorted(need.items()):
        hits = by_name.get(os.path.basename(exp).lower(), [])
        # prefer the candidate whose folder name resembles the expected one, then the shortest path
        hits = sorted(hits, key=lambda h: (-int(bool(a.prefer) and a.prefer.lower() in h.lower()), -int(os.path.basename(os.path.dirname(exp)).lower() in h.lower()), len(h)))
        (found.__setitem__(exp, hits[0]) if hits else lost.append(exp))
        print(f"{exp}  [{', '.join(sorted(repos))}]  ->  " + (f"found in the library as {hits[0]}" + (f" (+{len(hits) - 1} more)" if len(hits) > 1 else "") if hits else "NOT FOUND: truly missing"))
    if not a.apply:
        print(f"{len(found)} found under another path, {len(lost)} not found. Re-run with --apply to stage them.")
        return
    out = os.path.abspath(a.out or os.path.join(OUT, "build", "library-stage"))
    group = os.path.join(out, "Library")
    os.makedirs(group, exist_ok=True)
    for d in os.listdir(lib):
        if d != ".git" and os.path.isdir(os.path.join(lib, d)):
            link(os.path.join(lib, d), os.path.join(group, d))
    aliases = {}
    for exp, rel in found.items():
        dst = os.path.join(out, exp.replace("/", os.sep))
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(lib, rel.replace("/", os.sep)), dst)
        aliases["/".join(exp.split("/")[:2])] = "/".join(("Library/" + rel).split("/")[:-1])
    write_json(os.path.join(out, "aliases.json"), aliases)
    cfg["library_stage"] = out
    save_config(root, cfg)
    print(f"staged in {out}; assessment.json library_stage set. Run build_check.py again, then the real build.")


if __name__ == "__main__":
    main()
