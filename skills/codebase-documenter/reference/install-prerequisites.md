# install-prerequisites — make the machine ready before any other stage

Runs first in `full-run`, and whenever a script reports a missing tool. Everything is installed at **user level**: no administrator rights, no system settings changed.

| Tool | Needed for | Installed by |
| --- | --- | --- |
| Python 3.10+ | every script | you, in step 1 (the script below cannot install the interpreter it runs on) |
| pip | installing the rest | `install_prerequisites.py` (`ensurepip`) |
| MkDocs Material | the website (`build-site`, `verify-docs`) | `install_prerequisites.py` (`pip install --user`) |
| graphify | the code graph | `install_prerequisites.py` (`uv tool install`, else `pip install --user`) |
| graphify SQL extra (`graphifyy[sql]`) | graphify reads `.sql` files itself, so database objects join the communities of the code that uses them | `install_prerequisites.py` (`pip install --user`), pinned to the graphify version already installed so it never upgrades graphify |
| offline Mermaid | diagrams render without internet (Material otherwise fetches Mermaid from unpkg.com at view time) | `install_prerequisites.py` downloads `mermaid.min.js` once (about 3.5 MB, MIT) from jsDelivr into `~/.cache/codebase-documenter/`; every `build_site.py` copies it into the site. Blocked download: `offline_mermaid.py --from <mermaid.min.js>` |
| sqlglot | SQL parser fallback and the PostgreSQL preview (`sql_parse.py`) | `install_prerequisites.py` (`pip install --user`) |
| .NET SDK 8+ | Microsoft's T-SQL parser (ScriptDom) for `.sql` files and SQL inside C# strings; the assessment's Linux build checks | `install_prerequisites.py` with Microsoft's `dotnet-install` script, per user (`%LOCALAPPDATA%\Microsoft\dotnet` or `~/.dotnet`), current LTS. About 250 MB: **ask the user before running the installer when it is missing**. `--no-dotnet` skips it (SQL then parsed by sqlglot only, procedural T-SQL partly unparsed) |
| ScriptDom helper | the small parser program in `scripts/sqlscan` | built once by `install_prerequisites.py` (or on first use) into the per-user cache; restores one NuGet package (`Microsoft.SqlServer.TransactSql.ScriptDom`, MIT) from nuget.org |
| git | optional: change detection, graphify hooks | not installed automatically; report only |
| Docker or WSL | optional (assessment): real Linux builds | report only |
| api.nuget.org | optional (assessment `--online`): package frameworks, deprecation, advisories, licence history | report only (a reachability check) |
| LLM key | optional: community naming | read from environment variables; when none is set, the installer recommends OpenRouter + GLM 5.3 Flash and offers to save a pasted key (`--no-key-prompt` to skip the question) |

## 1. Python

1. Find a working interpreter, in this order: `python --version`, `python3 --version`, then on Windows `py -3 --version`. Use the first that prints **3.10 or newer**, and use that same command for every script in this skill.
   - Windows: a `python` that prints nothing or opens the Microsoft Store is the Store alias, not Python; treat it as missing.
2. If none qualifies, **ask the user once** before installing software, naming what will be installed and from where. Then use the platform's package manager:

   | Platform | Command | Notes |
   | --- | --- | --- |
   | Windows | `winget install -e --id Python.Python.3.12 --scope user` | User scope, no admin. winget may ask to accept its source terms: let the user confirm in their terminal. The new `python` is on PATH only in new terminals; until then use `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. |
   | macOS | `brew install python@3.12` | Without Homebrew: the installer from python.org, which the user runs. |
   | Debian / Ubuntu | `sudo apt-get install -y python3 python3-pip python3-venv` | Needs `sudo`: give the user the command to run themselves. |
   | Fedora / RHEL | `sudo dnf install -y python3 python3-pip` | Same. |

   If the package manager is missing or the install needs a password, stop and give the user the exact command. Never enter a password yourself.
3. Re-check with the full path if PATH has not refreshed.

## 2. Everything else

```bash
python <skill-base-dir>/scripts/install_prerequisites.py
```

It prints one line per tool (`ok` / `MISSING` / `absent` for optional ones), installs what is missing, re-checks, and ends with `READY` or `NOT READY` (exit code 1). It is safe to rerun. With `--check` it only reports.

| Message | Fix |
| --- | --- |
| `externally-managed` / PEP 668 (Homebrew or Debian Python) | Create a virtual environment as printed and run every script with that environment's `python`. Record the interpreter path in `codebase-docs.json` notes or memory. |
| graphify installed but `not on this shell's PATH` | Nothing to do: the scripts find it in the uv / pip user folders. New terminals see it after a restart. |
| graphify install fails on build tools (rare, tree-sitter wheels) | Upgrade pip (`python -m pip install -U pip`) and rerun. If that fails, report the last lines to the user. |
| `.NET SDK` download fails or is blocked | Install the SDK from https://dotnet.microsoft.com/download (or the client's software portal), open a new terminal, rerun. Until then SQL is parsed with sqlglot. |
| `ScriptDom helper build failed` | Usually no access to nuget.org: set `HTTPS_PROXY` or a NuGet source that mirrors nuget.org, then `python <skill>/scripts/sql_parse.py --build`. |
| `dotnet` installed but not found | Open a new terminal (the installer adds it to the user PATH); the scripts also look in the per-user folders directly. |
| Corporate proxy / no internet | Report it; the user sets `HTTPS_PROXY` or installs from an internal mirror. |

## 3. Tool versions and updates

The installer puts in the versions this skill was tested with (`scripts/data/tool_versions.json`: graphify, MkDocs
Material, sqlglot, Mermaid), never "latest", because a new graphify release once changed how `graph.json` is saved.
When a tested version has no build for the machine's Python, it installs the newest release and says so.

| Command | What it does |
| --- | --- |
| `install_prerequisites.py --check-updates` | Installed, tested and latest version of each tool; installs nothing. `npx -y github:MayankPunghal/Skills update` runs it after updating the skills, and `context.py` repeats its one-line `TOOLS:` summary for 30 days |
| `install_prerequisites.py --update` | Moves each installed tool that is not at its tested version (older or newer) to the tested version; never to an untested release |
| `tool_updates.py --offline` | The same report without the pypi.org / npmjs.org lookups (only public package names are sent) |

A newer release is reported, not installed. It becomes the tested version once both skills have been run with it on the
testbed; raise the version in `tool_versions.json` in the same pull request as any fix it needed.

## 4. Done when

`install_prerequisites.py --check` prints `READY`. `context.py` then stops reporting missing tools. Tick it in PROGRESS if the project already exists.
