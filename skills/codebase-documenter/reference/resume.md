# resume — continue an interrupted job

1. `python <skill>/scripts/context.py` → state + `NEXT`.
2. Read `docs/_notes/PROGRESS.md` (phases, open research areas, corrections log) and, if needed, the memory files of the agent runtime.
3. `python <skill>/scripts/research_notes.py status` → which notes are thin (template sections left).
4. Continue with the first open item. Do not re-read code an existing verified note already covers unless a correction is needed.
5. Same rules as before: no invention, everything linked, no secrets, silent work, one final summary.

Resume prompt a user can paste: *"Resume the documentation job: run the codebase-documenter `resume` command and continue with the next open item."*
