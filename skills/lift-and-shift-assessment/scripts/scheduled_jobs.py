"""Scheduled and background jobs of a source tree: what runs on a schedule or in the background, what triggers it, how often,
what it runs and whether the scheduler is Windows-only. Standard library only; shared by the codebase-documenter
(build-and-run operations section) and the migration-assessment scanner (scheduled jobs table and export).

    import scheduled_jobs as SJ
    jobs = SJ.scan(root)    # [{scheduler, name, schedule, target, file, line, windows_only, configured_by}]

Schedulers: Windows Task Scheduler (task XML exports, schtasks, Register-ScheduledTask), SQL Server Agent (sp_add_job /
sp_add_jobstep / sp_add_jobschedule in .sql or scripts, schedule decoded), Windows services (ServiceBase, UseWindowsService),
Hangfire (RecurringJob.AddOrUpdate, Cron.*), Quartz.NET (WithCronSchedule, WithSimpleSchedule, WithIdentity), .NET hosted /
background services (interval from PeriodicTimer / Task.Delay / Timer, or the config key it reads), Azure Functions timers,
Kubernetes CronJob, AWS EventBridge / serverless schedules, CI pipeline schedules, node-cron, Spring @Scheduled, schedule
settings in configuration (keys named *Cron* / *Schedule* / *Interval*), and console job projects with no schedule in the
repository (the trigger lives outside: Task Scheduler, SQL Agent, Control-M ...). Regular expressions over text: flags for
review, never enforced. Schedule expressions are shown; secrets are never read (only cron / interval / time values).
"""
import os
import re

MAX_BYTES = 2_500_000
SKIP_DIRS = {".git", ".vs", ".idea", "bin", "obj", "node_modules", "packages", "dist", "build", "out", "target", "vendor", ".venv",
             "venv", "__pycache__", "coverage", "graphify-out", "testresults", "artifacts", "publish"}
CODE = {".cs", ".vb", ".fs", ".java", ".kt", ".js", ".mjs", ".ts", ".py"}
SCRIPT = {".sql", ".ps1", ".psm1", ".cmd", ".bat", ".sh"}
CONF = {".json", ".yml", ".yaml", ".config", ".xml"}
CRON = r"(?:[\d*?/,\-LW#A-Z]+\s+){4,6}[\d*?/,\-LW#A-Z]+"
FREQ = {1: "once", 4: "daily", 8: "weekly", 16: "monthly", 32: "monthly (relative)", 64: "when SQL Agent starts", 128: "when the CPU is idle"}
SUBDAY = {1: "", 2: "second", 4: "minute", 8: "hour"}
HANGFIRE_CRON = {"minutely": "every minute", "hourly": "hourly", "daily": "daily", "weekly": "weekly", "monthly": "monthly", "yearly": "yearly",
                 "never": "never (manual)"}
JOB_PROJECT = re.compile(r"(?i)(job|jobs|batch|task|tasks|scheduler|cron|import|export|sync|etl|worker|nightly|daemon)")


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _timespan(expr):
    """TimeSpan.FromMinutes(5) / FromSeconds(30) / Task.Delay(60000) / "00:05:00" -> 'every 5 minutes'."""
    m = re.search(r"From(Milliseconds|Seconds|Minutes|Hours|Days)\s*\(\s*([\d.]+)", expr)
    if m:
        unit = m.group(1).lower().rstrip("s")
        return f"every {m.group(2)} {unit}{'' if m.group(2) == '1' else 's'}"
    m = re.search(r"\bnew\s+TimeSpan\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", expr)
    if m:
        h, mi, s = (int(x) for x in m.groups())
        return "every " + " ".join(f"{v} {u}" for v, u in ((h, "h"), (mi, "min"), (s, "s")) if v)
    m = re.search(r"Delay\s*\(\s*(\d{3,})\s*[,)]", expr)
    if m:
        ms = int(m.group(1))
        return f"every {ms // 60000} minutes" if ms % 60000 == 0 else f"every {ms / 1000:g} seconds"
    return ""


def _hangfire(fn, args):
    """Cron.Daily(2) -> 'daily at 02:00'; Cron.Hourly(15) -> 'hourly at :15'; Cron.Weekly(DayOfWeek.Monday, 3) -> 'weekly Monday at 03:00'."""
    a = [x.strip() for x in args.split(",") if x.strip()]
    nums = [int(x) for x in a if x.isdigit()]
    day = next((x.split(".")[-1] for x in a if "DayOfWeek." in x), "")
    base = HANGFIRE_CRON.get(fn.lower(), fn)
    if fn.lower() == "hourly" and nums:
        return f"hourly at :{nums[0]:02d}"
    if fn.lower() == "minuteinterval" and nums:
        return f"every {nums[0]} minutes"
    if fn.lower() == "hourinterval" and nums:
        return f"every {nums[0]} hours"
    if fn.lower() == "dayinterval" and nums:
        return f"every {nums[0]} days"
    f = fn.lower()
    if f == "monthly" and nums:  # Cron.Monthly(day[, hour[, minute]])
        hm = nums[1:] + [0, 0]
        return f"monthly on day {nums[0]} at {hm[0]:02d}:{hm[1]:02d}"
    if f == "yearly" and nums:  # Cron.Yearly(month[, day[, hour[, minute]]])
        rest = nums[1:] + [1, 0, 0][len(nums) - 1:]
        return f"yearly on {rest[0]}/{nums[0]} (day/month) at {rest[1]:02d}:{rest[2]:02d}"
    if nums and f in ("daily", "weekly"):  # Cron.Daily(hour[, minute]); Cron.Weekly(DayOfWeek[, hour[, minute]])
        hm = nums + [0]
        return f"{base}{' ' + day if day else ''} at {hm[0]:02d}:{hm[1]:02d}"
    return base + (f" {day}" if day else "")


def _agent_schedule(block):
    def num(name):
        m = re.search(rf"@{name}\s*=\s*(\d+)", block, re.I)
        return int(m.group(1)) if m else None
    ft, fi, st = num("freq_type"), num("freq_interval"), num("active_start_time")
    sub, subn = num("freq_subday_type"), num("freq_subday_interval")
    if ft is None:
        return ""
    s = FREQ.get(ft, f"freq_type {ft}")
    if ft == 4 and fi and fi > 1:
        s = f"every {fi} days"
    if sub and sub in (2, 4, 8) and subn:
        s += f", every {subn} {SUBDAY[sub]}{'s' if subn != 1 else ''}"
    if st is not None and not (sub and sub in (2, 4, 8)):
        t = f"{st:06d}"
        s += f" at {t[:2]}:{t[2:4]}"
    return s


class Scan:
    def __init__(self, root, skip_dirs=None):
        self.root = root
        self.skip = SKIP_DIRS | {s.lower() for s in (skip_dirs or [])}
        self.jobs = []
        self.projects = {}  # project dir -> (name, sdk, output type, has schedule)

    def add(self, scheduler, name, schedule, target, file, line, windows_only=False, configured_by=""):
        self.jobs.append({"scheduler": scheduler, "name": (name or "").strip()[:120], "schedule": (schedule or "").strip()[:160],
                          "target": (target or "").strip()[:160], "file": file, "line": line, "windows_only": windows_only,
                          "configured_by": configured_by})

    def run(self):
        for d, dirs, files in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if x.lower() not in self.skip and not x.startswith("."))
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                path = os.path.join(d, fn)
                rp = os.path.relpath(path, self.root).replace("\\", "/")
                if ext in (".csproj", ".vbproj", ".fsproj"):
                    self.project(rp, path)
                    continue
                if ext not in CODE | SCRIPT | CONF:
                    continue
                if re.search(r"(?i)\.min\.js$|(^|/)wwwroot/lib/|\.designer\.cs$|package-lock\.json$|\.deps\.json$", rp):
                    continue
                try:
                    if os.path.getsize(path) > MAX_BYTES:
                        continue
                    raw = open(path, "rb").read()
                    # Task Scheduler exports (schtasks /query /xml, "Export...") and some scripts are UTF-16
                    text = raw.decode("utf-16", errors="replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="replace")
                except OSError:
                    continue
                if ext in CODE:
                    self.code(rp, ext, text)
                if ext in SCRIPT:
                    self.script(rp, text)
                if ext in CONF:
                    self.conf(rp, ext, text)
        self.console_jobs()
        used = " ".join(j["configured_by"] for j in self.jobs if j["scheduler"] != "Schedule setting")
        self.jobs = [j for j in self.jobs if j["scheduler"] != "Schedule setting" or not re.search(rf"[`:]{re.escape(j['name'])}[`\s(]", used)]
        return sorted(self.jobs, key=lambda j: (j["scheduler"], j["file"], j["line"]))

    # ------------------------------------------------------------ projects
    def project(self, rp, path):
        try:
            t = open(path, encoding="utf-8-sig", errors="replace").read()
        except OSError:
            return
        sdk = (re.search(r'<Project\s+Sdk="([^"]+)"', t) or [None, ""])[1]
        out = (re.search(r"<OutputType>\s*(\w+)", t) or [None, ""])[1]
        self.projects[os.path.dirname(rp)] = (os.path.splitext(os.path.basename(rp))[0], sdk, out.lower(), rp)

    def console_jobs(self):
        """A console project named like a job, with nothing in the repository that schedules it: the trigger is outside."""
        scheduled = {os.path.dirname(j["file"]) for j in self.jobs}
        runs = " ".join(j["target"] for j in self.jobs).lower()
        for pdir, (name, sdk, out, rp) in self.projects.items():
            if out != "exe" or "Web" in sdk or "Test" in name or not JOB_PROJECT.search(name):
                continue
            if any(s == pdir or s.startswith(pdir + "/") for s in scheduled) or re.search(rf"\b{re.escape(name.lower())}(\.exe|\.dll)?\b", runs):
                continue  # scheduled in this repository (its own code, or a Task Scheduler / SQL Agent entry that runs it)
            self.add("Console job (trigger outside the repository)", name, "not in the repository: ask who runs it, when and where",
                     f"{name} executable", rp, 1, windows_only=False, configured_by="external scheduler (Task Scheduler, SQL Agent, Control-M, cron ...)")

    # ------------------------------------------------------------ code
    def code(self, rp, ext, text):
        cls = None
        if ext in (".cs", ".vb"):
            for m in re.finditer(r"(?:class\s+(\w+)[^{;]*?:\s*[^{;]*?\b(BackgroundService|IHostedService|ServiceBase)\b)|"
                                 r"(?:Class\s+(\w+)\s*\r?\n\s*Inherits\s+(ServiceBase|BackgroundService))", text):
                cls = m.group(1) or m.group(3)
                base = m.group(2) or m.group(4)
                body = text[m.end():m.end() + 6000]
                if base == "ServiceBase":
                    self.add("Windows service", cls, "runs continuously (service control manager)", cls, rp, _line(text, m.start()), True,
                             "installed with sc.exe / InstallUtil / installer")
                    continue
                every = ""
                cfg = ""
                for tm in re.finditer(r"PeriodicTimer\s*\(([^;]+)|Task\.Delay\s*\(([^;]+)|new\s+(?:System\.Threading\.)?Timer\s*\(([^;]+)", body):
                    expr = next(g for g in tm.groups() if g)
                    every = _timespan(expr)
                    if every:
                        break
                    var = re.match(r"\s*(\w+)", expr)  # Task.Delay(delay, ...) -> var delay = TimeSpan.FromSeconds(config.GetValue("X", 5))
                    if var:
                        dm = re.search(rf"\b{var.group(1)}\s*=\s*([^;]+);", body)
                        if dm:
                            every = _timespan(dm.group(1))
                            km = re.search(r"""GetValue\s*(?:<[^>]+>)?\s*\(\s*["']([\w:.\-]+)["']\s*(?:,\s*([\d.]+))?""", dm.group(1))
                            if km:
                                cfg = f"`{km.group(1)}`" + (f" (default {km.group(2)})" if km.group(2) else "")
                                unit = re.search(r"From(\w+?)s?\s*\(", dm.group(1))
                                n, u = km.group(2) or "?", (unit.group(1).lower() if unit else "")
                                every = f"every {n} {u}{'' if n == '1' or not u else 's'}".strip() + (" by default" if km.group(2) else "")
                        if every:
                            break
                en = re.search(r"""GetValue\s*(?:<[^>]+>)?\s*\(\s*["']([\w:.\-]*Enabled)["']\s*(?:,\s*(true|false))?""", body)
                off = False
                if en:
                    off = en.group(2) == "false"
                    cfg = (cfg + ", " if cfg else "") + f"`{en.group(1)}` switches it on" + (" (default false: off unless configured)" if off else "")
                sched = every or "runs continuously while the application runs"
                self.add("Hosted / background service", cls, ("off by default; when enabled " + sched) if off else sched, cls, rp,
                         _line(text, m.start()), False, cfg or "registered with AddHostedService")
            if re.search(r"\.UseWindowsService\s*\(", text):
                i = text.find("UseWindowsService")
                self.add("Windows service", os.path.basename(os.path.dirname(rp)) or rp, "runs continuously (service control manager)",
                         "generic host", rp, _line(text, i), True, "UseWindowsService()")
        # Hangfire
        for m in re.finditer(r"(?:RecurringJob|\w*[Rr]ecurringJob\w*)\.AddOrUpdate\s*(?:<(\w+)>)?\s*\(([^;]+);", text):
            args = m.group(2)
            ident = (re.match(r"""\s*["']([^"']+)["']""", args) or [None, ""])[1]
            tgt = re.search(r"(?:(\w+)|\(\s*\))\s*=>\s*([\w.]+)\s*\(", args)
            cron = re.search(r"Cron\.(\w+)\s*\(([^)]*)\)", args)
            lit = re.search(rf"""["']({CRON})["']""", args)
            sched = _hangfire(cron.group(1), cron.group(2)) if cron else (f"cron `{lit.group(1)}`" if lit else "")
            key = re.search(r"""(?:Configuration|config|_config)\s*\[\s*["']([\w:.\-]+)["']|GetValue\s*<[^>]+>\s*\(\s*["']([\w:.\-]+)["']""", args)
            call = ""
            if tgt:  # x => x.Run() on RecurringJob.AddOrUpdate<Cleanup>: the lambda parameter is the job class
                p = tgt.group(1)
                call = tgt.group(2)[len(p) + 1:] if p and tgt.group(2).startswith(p + ".") else tgt.group(2)
            target = ".".join(x for x in (m.group(1), call) if x)
            self.add("Hangfire", ident or target, sched or ("from configuration" if key else "?"), target, rp, _line(text, m.start()), False,
                     f"`{key.group(1) or key.group(2)}`" if key else "code (RecurringJob.AddOrUpdate)")
        # Quartz
        for m in re.finditer(r"WithCronSchedule\s*\(\s*\"([^\"]+)\"|WithSimpleSchedule\s*\(([^;]+?)\)\s*[.;)]", text):
            near = text[text.rfind(";", 0, m.start()) + 1:m.start()]  # the same builder statement
            ident = re.findall(r"WithIdentity\s*\(\s*\"([^\"]+)\"", near)
            job = re.findall(r"(?:JobBuilder\.Create|AddJob|ForJob)\s*<\s*(\w+)\s*>", near)
            if m.group(1):
                sched = f"cron `{m.group(1)}`"
            else:
                iv = re.search(r"WithInterval(?:In)?(Seconds|Minutes|Hours)\s*\(\s*(\d+)", m.group(2))
                sched = f"every {iv.group(2)} {iv.group(1).lower()}" if iv else "simple schedule"
            self.add("Quartz.NET", ident[-1] if ident else (job[-1] if job else ""), sched, job[-1] if job else "", rp, _line(text, m.start()))
        for m in re.finditer(r"\[TimerTrigger\s*\(\s*\"([^\"]+)\"", text):
            fn = re.search(r"\[(?:Function|FunctionName)\s*\(\s*(?:nameof\((\w+)\)|\"([^\"]+)\")", text[max(0, m.start() - 400):m.start() + 50])
            self.add("Azure Functions timer", (fn.group(1) or fn.group(2)) if fn else "", f"cron `{m.group(1)}`", "", rp, _line(text, m.start()))
        for m in re.finditer(r"@Scheduled\s*\(([^)]*)\)", text):
            self.add("Spring @Scheduled", "", m.group(1), "", rp, _line(text, m.start()))
        for m in re.finditer(r"\bcron\.schedule\s*\(\s*['\"]([^'\"]+)", text):
            self.add("node-cron", "", f"cron `{m.group(1)}`", "", rp, _line(text, m.start()))

    # ------------------------------------------------------------ scripts and SQL
    def script(self, rp, text):
        for m in re.finditer(r"(?is)sp_add_job\s+@job_name\s*=\s*N?'([^']+)'", text):
            name = m.group(1)
            rest = text[m.end():m.end() + 4000]
            stop = re.search(r"(?is)sp_add_job\s+@job_name", rest)
            rest = rest[:stop.start()] if stop else rest
            cmds = re.findall(r"(?is)@command\s*=\s*N?'((?:[^']|'')*)'", rest)
            sch = re.search(r"(?is)sp_add_(?:job)?schedule\b(.*?)(?:;|\bEXEC\b|$)", rest)
            self.add("SQL Server Agent", name, _agent_schedule(sch.group(1)) if sch else "no schedule in the script",
                     "; ".join(c.replace("''", "'").strip()[:120] for c in cmds), rp, _line(text, m.start()), False, "msdb job (sp_add_job); SQL Server only, none on PostgreSQL")
        for m in re.finditer(r"(?i)schtasks(?:\.exe)?\s+/create\b([^\r\n]*)", text):
            a = m.group(1)
            tn = re.search(r'(?i)/tn\s+"?([^"/]+)"?', a)
            tr = re.search(r'(?i)/tr\s+"([^"]+)"|/tr\s+(\S+)', a)
            sc = re.search(r"(?i)/sc\s+(\w+)", a)
            mo = re.search(r"(?i)/mo\s+(\w+)", a)
            st = re.search(r"(?i)/st\s+([\d:]+)", a)
            sched = " ".join(x for x in ((sc.group(1).lower() if sc else ""), (f"every {mo.group(1)}" if mo else ""), (f"at {st.group(1)}" if st else "")) if x)
            self.add("Windows Task Scheduler", tn.group(1).strip() if tn else "", sched, (tr.group(1) or tr.group(2)) if tr else "", rp,
                     _line(text, m.start()), True, "schtasks /create")
        for m in re.finditer(r"(?i)Register-ScheduledTask\b([^\r\n]*)", text):
            tn = re.search(r'(?i)-TaskName\s+["\']?([^"\'\s]+)', m.group(1))
            near = text[max(0, m.start() - 1500):m.start()]
            trig = re.findall(r"(?i)New-ScheduledTaskTrigger\s+([^\r\n]+)", near)
            act = re.findall(r"(?i)New-ScheduledTaskAction\s+([^\r\n]+)", near)
            self.add("Windows Task Scheduler", tn.group(1) if tn else "", trig[-1].strip() if trig else "", act[-1].strip()[:120] if act else "", rp,
                     _line(text, m.start()), True, "Register-ScheduledTask")
        for m in re.finditer(r"(?im)^\s*([\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+)\s+(\S.*)$", text) if rp.endswith((".sh",)) or "crontab" in rp.lower() else []:
            self.add("cron", "", f"cron `{m.group(1)}`", m.group(2)[:120], rp, _line(text, m.start()))

    # ------------------------------------------------------------ configuration
    def conf(self, rp, ext, text):
        low = rp.lower()
        if ext == ".xml" and "schemas.microsoft.com/windows/2004/02/mit/task" in text:
            trig = []
            for t in re.finditer(r"(?s)<(CalendarTrigger|TimeTrigger|BootTrigger|LogonTrigger|IdleTrigger|EventTrigger)>(.*?)</\1>", text):
                body = t.group(2)
                start = re.search(r"<StartBoundary>([^<]+)", body)
                days = re.search(r"<DaysInterval>(\d+)", body)
                rep = re.search(r"<Repetition>.*?<Interval>([^<]+)", body, re.S)
                kind = "weekly" if "<ScheduleByWeek>" in body else "monthly" if "<ScheduleByMonth>" in body else "daily" if "<ScheduleByDay>" in body else t.group(1)
                trig.append(" ".join(x for x in (kind if t.group(1) == "CalendarTrigger" else t.group(1), f"every {days.group(1)} days" if days and days.group(1) != "1" else "",
                                                 f"from {start.group(1)}" if start else "", f"repeat {rep.group(1)}" if rep else "") if x))
            cmd = re.search(r"<Command>([^<]+)</Command>", text)
            args = re.search(r"<Arguments>([^<]+)</Arguments>", text)
            uri = re.search(r"<URI>([^<]+)</URI>", text)
            self.add("Windows Task Scheduler", (uri.group(1) if uri else os.path.splitext(os.path.basename(rp))[0]), "; ".join(trig) or "?",
                     (cmd.group(1) + (" " + args.group(1) if args else "")) if cmd else "", rp, 1, True, "task XML export")
            return
        if ext in (".yml", ".yaml"):
            if re.search(r"(?m)^kind:\s*CronJob\b", text):
                name = re.search(r"(?m)^\s{2}name:\s*([\w.\-]+)", text)
                sch = re.search(r"""(?m)^\s*schedule:\s*["']?([^"'\n]+)""", text)
                img = re.search(r"(?m)^\s*image:\s*(\S+)", text)
                self.add("Kubernetes CronJob", name.group(1) if name else "", f"cron `{sch.group(1).strip()}`" if sch else "", img.group(1) if img else "",
                         rp, _line(text, sch.start()) if sch else 1)
            for m in re.finditer(r"""(?m)^\s*-?\s*cron:\s*["']([^"']+)["']""", text):
                ci = low.startswith(".github/") or "pipeline" in low or low.startswith((".gitlab", "azure-pipelines"))
                self.add("CI pipeline schedule" if ci else "cron (YAML)", os.path.basename(rp), f"cron `{m.group(1)}`", "", rp, _line(text, m.start()))
            for m in re.finditer(r"""(?mi)^\s*(?:ScheduleExpression|schedule|rate):\s*["']?((?:rate|cron)\([^)]+\))""", text):
                self.add("AWS EventBridge schedule", "", m.group(1), "", rp, _line(text, m.start()))
            return
        if ext == ".json" and re.search(r"(?i)(settings|appsettings|jobsettings|config)[\w.\-]*\.json$", os.path.basename(rp)) and not re.search(r"(?i)launchsettings", rp):
            for m in re.finditer(r"""(?i)"([\w.\-]*(?:cron|schedule|interval|pollseconds|pollminutes|delayseconds|frequency)[\w.\-]*)"\s*:\s*("[^"]{1,60}"|\d+)""", text):
                val = m.group(2).strip('"')
                if re.search(r"(?i)retry|backoff|timeout|cache|expir|ttl|lockout|session", m.group(1)):
                    continue  # waits and lifetimes, not schedules
                if not re.fullmatch(rf"{CRON}|\d+|[\d:.]+|(rate|cron)\(.+\)|@\w+|every .+|\w+ly", val, re.I):
                    continue
                self.add("Schedule setting", m.group(1), val, "", rp, _line(text, m.start()), False, "configuration key")


def scan(root, skip_dirs=None):
    return Scan(root, skip_dirs).run()


if __name__ == "__main__":
    import sys
    for j in scan(sys.argv[1] if len(sys.argv) > 1 else "."):
        print(f"{j['scheduler']:<34} {j['name'][:34]:<34} {j['schedule'][:40]:<40} {j['target'][:40]:<40} {j['file']}:{j['line']}"
              + (" [Windows]" if j["windows_only"] else ""))
