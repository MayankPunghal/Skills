"""Open questions for the client, DevOps and the dev lead, written from the assessment data.

    py <skill>/scripts/build_open_questions.py [--out DIR]

Writes three documents, each as .md and an .html twin, into assessment/documents (or DIR):
    <client>-open-questions.md                 the full list, with what each question changes and the evidence
    <client>-open-questions-short.md           the short list
    <client>-questions-for-client-email.md     the client questions as an email the user can send

Inputs (all in the workspace; a missing input just leaves its questions out):
    assessment.json                  intake answers, intake.client_updates, intake.release_process, intake.branch_notes,
                                     intake.environments_confirmed, client, prepared_by, docx_template
    assessment/solutions/index.json  solutions, environments, environments_confirmed, environments_assumed
    assessment/solutions/third_party.json   integrations and licensed components
    assessment/build/index.json      static and real build results and the workarounds used in the build copy
    assessment/infra/address_roles.json     every internal and public address with its likely role (never values)
    assessment/infra/servers.json    the DevOps server list (names, OS, environment, hypervisor, roles)
    assessment/estimate.json         the estimate total
    assessment/documents/meta.json   the draft revision
    assessment/documents/built.json  the report file names (revision fallback)
    assessment/infra/mapping-check.json  optional: findings of check_mapping.py, when the client returned the mapping workbook

Optional fields in assessment.json (set them with intake.py --open-question and setup_assessment.py --client-contact):
    open_questions_extra   list of objects {"question", "why", "who", "status"}
                           question: the text; why: what it changes (hours or section);
                           who: "client", "DevOps", "DB team" or "dev lead" (default "dev lead");
                           status: "open" (default), "waiting" (the client said it will answer later) or "closed".
    client_contact         the name the email greets (for example "Sam"); the email says "Hello," when absent.

Answer status rules: an intake answer other than 'unknown' closes its question. An intake answer of 'unknown' leaves it open.
A client_updates row closes or waits on a question whose key word appears in its topic; the row is "waiting" when its
answer says the client will come back (or when its optional 4th element is "waiting").
Facts the server list or the scans already hold are not asked (for example the Windows versions and the hypervisors).

Never prints a secret value: setting names, file names, server names and addresses only.
"""
import argparse
import collections
import datetime
import os
import re

import intake as I
from _common import OUT, load_config, read_json, slug, utf8_stdout
from _mdhtml import write_pair

GROUPS = {"client": "client", "DevOps": "devops", "DB team": "devops", "dev lead": "dev"}

# who answers an intake question that the answers do not settle (default: dev lead)
WHO = {
    "environments": "client", "environments_differ": "client", "current_hosting": "client",
    "windows_versions": "client", "test_environment": "client", "smoke_tests": "client",
    "testing_by": "client", "public_endpoints": "client", "missing_references": "client",
    "secrets_owner": "client", "source_access": "client", "source_settings": "client",
    "maintenance_windows": "client", "regression_tests": "client", "credential_rotation_owner": "client",
    "ip_allowlists": "client", "licence_terms": "client", "job_schedules": "client",
    "aws_landing_zone": "DevOps", "aws_connectivity": "DevOps", "aws_region": "DevOps",
    "devops_mechanism": "DevOps", "hypercare_days": "DevOps", "parallel_run_days": "DevOps",
    "devops_notes": "DevOps", "build_agent": "DevOps", "artifact_format": "DevOps",
    "ci_platform_target": "DevOps", "ci_platform_today": "DevOps", "ad_domain": "DevOps",
    "mail_relay": "DevOps", "file_shares": "DevOps", "machine_bound": "DevOps", "private_feeds": "DevOps",
    "database_location": "DB team",
}
# a client_updates topic that answers an intake question contains this word
CU_KEY = {"environments": "environment", "environments_differ": "environment", "missing_references": "library"}
PAYMENT_EMAIL = re.compile(r"(?i)stripe|braintree|payflow|paypal|kount|worldpay|adyen|sendgrid|mailgun|sharepoint|smtp")
WAIT_TEXT = re.compile(r"(?i)\bwill\b.{0,80}\b(email|send|check|come back|supply|confirm|tell|follow)")
REPORT_CLOSED = "closed"


def P(root, *parts):
    return os.path.join(root, OUT, *parts)


def one_line(text, n=220):
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def cell(text):
    return one_line(text, 300).replace("|", "/")


def counted(counter):
    return ", ".join(f"{v} {k}" for k, v in counter.most_common())


def item(who, q, changes, evidence="", status="open", answer="", decision=False, key=""):
    return {"who": who, "group": GROUPS.get(who, "dev"), "q": one_line(q, 400), "changes": one_line(changes, 400),
            "evidence": one_line(evidence, 400), "status": status, "answer": one_line(answer, 300), "decision": decision, "key": key}


def cu_rows(cfg):
    """client_updates rows: [topic, answer, effect(, status)]."""
    return [r for r in (cfg.get("intake") or {}).get("client_updates") or [] if isinstance(r, (list, tuple)) and len(r) >= 3]


def cu_match(cfg, key):
    """The client_updates row that answers a question with this key word, with its status."""
    for r in cu_rows(cfg):
        if key and key.lower() in str(r[0]).lower():
            status = r[3] if len(r) > 3 else ("waiting" if WAIT_TEXT.search(str(r[1])) else "closed")
            return {"status": status, "answer": r[1], "effect": r[2], "topic": r[0]}
    return None


def load_inputs(root):
    d = {
        "servers": read_json(P(root, "infra", "servers.json"), {}) or {},
        "roles": read_json(P(root, "infra", "address_roles.json"), {}) or {},
        "solutions": read_json(P(root, "solutions", "index.json"), {}) or {},
        "third": read_json(P(root, "solutions", "third_party.json"), {}) or {},
        "build": read_json(P(root, "build", "index.json"), {}) or {},
        "estimate": read_json(P(root, "estimate.json"), {}) or {},
        "meta": read_json(P(root, "documents", "meta.json"), {}) or {},
        "built": read_json(P(root, "documents", "built.json"), {}) or {},
        "mapping": read_json(P(root, "infra", "mapping-check.json"), None),
    }
    return d


def facts(root, cfg, d):
    """What we hold: the server list, the scans, the build and the estimate. Returned as sentences for 'What we know'."""
    out = []
    srv = d["servers"]
    servers = srv.get("servers") or []
    if servers:
        out.append(f"The server list ({srv.get('source', 'DevOps list')}) has {len(servers)} servers: "
                   f"{counted(collections.Counter(s.get('environment', '?') for s in servers))}. "
                   f"Operating systems: {counted(collections.Counter(s.get('os_family', '?') for s in servers))}. "
                   f"Servers with an IP address: {sum(1 for s in servers if s.get('ip'))} of {len(servers)}.")
    sols = (d["solutions"] or {}).get("solutions") or []
    if sols:
        repos = len({s.get("repo") for s in sols})
        projects = sum(len(s.get("projects") or []) for s in sols)
        out.append(f"Scope: {repos} repositories, {len(sols)} solutions, {projects} projects in solution files. "
                   f"Projects in no solution file are not estimated.")
    bs = (d["build"] or {}).get("solutions") or []
    if bs:
        passed = sum(1 for s in bs if (s.get("real") or {}).get("status") == "PASS")
        wa = sum(1 for s in bs if (s.get("real") or {}).get("workarounds"))
        out.append(f"Build check: {passed} of {len(bs)} solutions pass the real build; {wa} pass only with a workaround in the build copy.")
    tp = (d["third"] or {}).get("solutions") or []
    if tp:
        lic = sorted({i["name"] for s in tp for i in s.get("licensed_and_integrations", []) if i.get("kind") == "licensed component"})
        integ = sum(1 for s in tp for i in s.get("licensed_and_integrations", []) if i.get("kind") == "integration")
        out.append(f"Third parties: {integ} outbound integrations found in the code; licensed components: {', '.join(lic) or 'none'}.")
    est = d["estimate"] or {}
    if est.get("total"):
        out.append(f"Estimate (DRAFT): {est['total']['low']:g}-{est['total']['high']:g} developer hours "
                   f"({est.get('days_low', 0):g}-{est.get('days_high', 0):g} days of {est.get('day_hours', 8)} h), pipelines not included.")
    return out


def fact_for(qid, d):
    """A fact the data already holds for an intake question (so it is not asked)."""
    servers = (d["servers"] or {}).get("servers") or []
    if not servers:
        return ""
    if qid == "windows_versions":
        win = collections.Counter(s.get("os") for s in servers if s.get("os_family") == "windows")
        return f"Server list: {counted(win)}" if win else ""
    if qid == "current_hosting":
        hv = collections.Counter(s.get("hypervisor") or "not stated" for s in servers)
        return f"Server list hypervisors: {counted(hv)}"
    return ""


def intake_items(root, cfg, d, sig, answered_out):
    """Intake questions that apply: answered ones are recorded as closed, 'unknown' or unanswered ones are open."""
    ans = cfg.get("intake") or {}
    out = []
    for q in I.questions():
        qid = q["id"]
        if not I.applies(q, ans, sig):
            continue
        v = ans.get(qid)
        if I.answered(ans, qid) and v != "unknown":
            answered_out.append((q["ask"], v))
            continue
        fact = fact_for(qid, d)
        if fact:
            answered_out.append((q["ask"], f"not asked: {fact}"))
            continue
        cu = cu_match(cfg, CU_KEY.get(qid, ""))
        if cu:
            if cu["status"] == "closed":
                answered_out.append((q["ask"], f"{cu['answer']} ({cu['effect']})"))
                continue
            out.append(item(WHO.get(qid, "dev lead"), q["ask"], q.get("affects", ""), I.evidence(q, sig) or "client call notes",
                            status="waiting", answer=cu["answer"], key=qid))
            continue
        ev = I.evidence(q, sig) or "the intake answer is unknown"
        out.append(item(WHO.get(qid, "dev lead"), q["ask"], q.get("affects", ""), ev, key=qid))
    return out


def library_item(cfg, d):
    """Solutions whose build depends on another folder layout (a path mismatch or another repository's output)."""
    hits = []
    for s in (d["build"] or {}).get("solutions") or []:
        kinds = [w.get("kind", "") for w in (s.get("real") or {}).get("workarounds") or []]
        if any(k in ("setting points outside the repository", "another repository's build output", "file missing from the repository")
               for k in kinds) or any("reference DLL not found" in i for i in s.get("static", {}).get("issues", [])):
            hits.append(s["id"])
    if not hits:
        return None
    cu = cu_match(cfg, "library")
    status = cu["status"] if cu and cu["status"] != "closed" else ("open" if not cu else "closed")
    return item("client", "Which folder layout do the Jenkins build agents use today for these paths? (The builds pass here with a workaround in a copy.)",
                "Section 5.1 (build prerequisites) and the Build sheet. Builds pass with the workaround, so no hours change; the layout matters when the build moves to the AWS pipeline.",
                f"{len(hits)} solutions use paths that the current Library repository does not have: {', '.join(hits[:6])}{' and more' if len(hits) > 6 else ''}.",
                status=status, answer=(cu or {}).get("answer", ""), key="library")


def proxy_items(d):
    """Outbound proxies named in the code, and whether the server list has any proxy server."""
    prox = [a for a in (d["roles"] or {}).get("addresses") or [] if str(a.get("role", "")).startswith("Outbound proxy")]
    if not prox:
        return []
    servers = (d["servers"] or {}).get("servers") or []
    in_list = [s["name"] for s in servers if "proxy" in s.get("name", "").lower() or any(r.get("role") == "proxy" for r in s.get("roles", []))]
    addrs = ", ".join(f"{a['address']} port {', '.join(str(p) for p in a.get('ports') or []) or 'not stated'}" for a in prox)
    return [item("DevOps", "Do the supplier outbound proxies move with the applications, or do they stay where they are?",
                 "Supplier allow-lists. If they move, suppliers must be told the new addresses; section 5.3 and the network sections.",
                 f"Proxies in the code: {addrs}. Proxy servers in the server list: {len(in_list)} of {len(servers)}.")]


def unknown_purpose_items(d):
    """Public addresses whose purpose the code does not show (role starts with 'Allow-listed')."""
    odd = [a for a in (d["roles"] or {}).get("addresses") or []
           if a.get("type") == "public IP" and str(a.get("role", "")).startswith("Allow-listed")]
    if not odd:
        return []
    names = ", ".join(a["address"] for a in odd)
    where = "; ".join(f"{a['address']} in {', '.join(a.get('solutions_repos') or []) or 'the code'}" for a in odd)
    return [item("DevOps", f"What are these public addresses used for, and does a supplier or partner allow-list them? ({names})",
                 "Allow-lists: the new AWS addresses must be registered if they are allow-listed. Section 5.3.",
                 f"Found in: {where}. The code does not show the purpose.")]


def provider_items(cfg, d):
    """Payment, email and file-sharing providers: do they accept calls only from our server addresses?"""
    names = set()
    for s in (d["third"] or {}).get("solutions") or []:
        for i in s.get("licensed_and_integrations", []):
            if i.get("kind") == "integration" and PAYMENT_EMAIL.search(i.get("name", "")):
                names.add(i["name"])
    if not names:
        return []
    allow = (cfg.get("intake") or {}).get("ip_allowlists")
    status = "closed" if allow == "no" else "open"
    return [item("client", "Do any of these providers accept calls only from our server addresses? If yes, the new AWS addresses must be registered with them.",
                 "Section 5.3 and wave 0. Changes the source address of outbound calls after the move.",
                 f"Found in the code: {', '.join(sorted(names))}.", status=status)]


def release_items(cfg):
    rows = (cfg.get("intake") or {}).get("release_process") or []
    out = []
    text = " ".join(" ".join(map(str, r)) for r in rows if isinstance(r, (list, tuple)))
    m = re.search(r"every (\d+) minutes", text)
    if m:
        out.append(item("DevOps", f"Does AWS keep the copy-based release model (Jenkins drop, a copy every {m.group(1)} minutes, each server picks up), or does it get replaced?",
                        "Sections 7 and 8 (release steps). The estimate has no pipeline hours either way.",
                        "Release process as the client described it (intake release_process). No pipeline files exist in the repositories."))
    for r in rows:
        if isinstance(r, (list, tuple)) and re.search(r"(?i)not specified|to be confirmed", " ".join(map(str, r))):
            out.append(item("DevOps", f"Confirm the release process row '{r[0]}': the client left part of it open.",
                            "Section 3 and section 7 (release steps); where the server sits in the target.", one_line(r[1], 200)))
    return out


def mapping_items(d):
    """Findings of check_mapping.py (contradictions between the client's answers, the DevOps list and the code)."""
    m = d["mapping"]
    if not m:
        return []
    rows = m.get("findings", m) if isinstance(m, dict) else m
    out = []
    for f in rows if isinstance(rows, list) else []:
        if not isinstance(f, dict):
            continue
        text = f.get("question") or f.get("finding") or f.get("text")
        if text and f.get("severity", "CHECK") != "INFO":
            where = f" ({f['where']})" if f.get("where") else ""
            out.append(item("client", f"{f.get('check', 'Mapping')}{where}: {text}. Please confirm or correct.",
                            f.get("changes", "Which servers each workload moves with (sections 8 and 9)."), f.get("evidence", "check_mapping.py on the returned mapping workbook.")))
    return out


def ours_items(d):
    """Build gaps we worked around in the build copy: not asked, flagged in the workbook."""
    out = []
    for s in (d["build"] or {}).get("solutions") or []:
        wa = (s.get("real") or {}).get("workarounds") or []
        if not wa:
            continue
        acts = "; ".join(f"{w.get('kind', 'workaround')}: {one_line(w.get('action', ''), 140)}" for w in wa[:3])
        out.append(item("dev lead", f"{s['id']}: build copy workaround",
                        "Build sheet: solution shows PASS with workaround (contingent pass).", acts, status="closed", answer="worked around in the build copy"))
    return out


def decision_items(cfg, d):
    out = []
    sols = (d["solutions"] or {}).get("solutions") or []
    unconf = [s["id"] for s in sols if not s.get("environments_confirmed")]
    if unconf:
        out.append(item("dev lead", f"Confirm one environment per solution for the {len(sols)} solutions (accepted so far). Confirm with the user before the document can be final.",
                        "Workloads and the estimate: each extra environment adds the workload hours in estimate.json.",
                        f"{len(unconf)} solutions have the environment assumption unconfirmed.", decision=True))
    bn = (cfg.get("branch_notes") or {})
    if bn:
        out.append(item("dev lead", f"Accepted assumption: the branches selected for {len(bn)} repositories (sheet Branches) are the ones assessed.",
                        "Which code the scan and the estimate read.", "intake branch_notes; the client named no default branch.", status="closed", answer="accepted", decision=True))
    return out


def extra_items(cfg):
    out = []
    for e in cfg.get("open_questions_extra") or []:
        if not isinstance(e, dict) or not e.get("question"):
            continue
        who = e.get("who") or "dev lead"
        it = item(who, e["question"], e.get("why", ""), "added by hand", status=e.get("status") or "open")
        it["decision"] = who == "dev lead" and it["status"] == "open" and "decide" in e["question"].lower()
        out.append(it)
    return out


def build_all(root, cfg, d):
    sig = I.signals(root)
    answered = []
    ideas = []
    ideas += intake_items(root, cfg, d, sig, answered)
    lib = library_item(cfg, d)
    if lib:
        ideas.append(lib)
        # the library item asks the same thing as the intake's missing_references question: keep one
        ideas = [x for x in ideas if x.get("key") != "missing_references"]
    ideas += proxy_items(d) + unknown_purpose_items(d) + provider_items(cfg, d) + release_items(cfg)
    ideas += mapping_items(d) + decision_items(cfg, d) + extra_items(cfg)
    # keep the first of duplicate questions (intake key wins over derived)
    seen, items = set(), []
    for it in ideas:
        k = it["q"][:60]
        if k in seen:
            continue
        seen.add(k)
        items.append(it)
    return items, ours_items(d), answered


def header(cfg, d, today):
    rev = (d["meta"] or {}).get("revision") or (d["built"] or {}).get("revision") or "?"
    docx = os.path.basename((d["built"] or {}).get("docx") or "") or f"{slug(cfg.get('client'))}-lift-and-shift-assessment.docx"
    est = (d["estimate"] or {}).get("total") or {}
    nsol = len((d["solutions"] or {}).get("solutions") or [])
    hours = f", estimate {est['low']:g}-{est['high']:g} h" if est else ""
    return (f"DRAFT, {today}. For the report `{docx}` (Draft {rev}: {nsol} solutions{hours}). "
            f"Nothing is final until you say so.")


def group(items, g, status=None):
    return [i for i in items if i["group"] == g and (status is None or i["status"] == status) and not i["decision"]]


def full_md(cfg, d, items, ours, answered, today):
    client = cfg.get("client") or "Client"
    L = [f"# {client} .NET apps: open questions", "", header(cfg, d, today), ""]
    L += ["## What we know and what we don't", ""]
    for f in facts(cfg.get("_root", ""), cfg, d):
        L.append(f"- {f}")
    for r in cu_rows(cfg):
        if len(r) < 4 and not WAIT_TEXT.search(str(r[1])):
            L.append(f"- **{r[0]} ({client}):** {one_line(r[1])} Effect: {one_line(r[2])}")
    for q, v in answered:
        if str(v).startswith("not asked"):
            L.append(f"- **{one_line(q, 140)}** {one_line(v, 200)}")
    L.append(f"- {len(answered)} intake questions are answered and not asked again (the answers are in assessment.json).")
    L.append("")
    L += [f"## Questions for {client} (client)", ""]
    qs = group(items, "client", "open")
    for i in qs:
        L += [f"- **{i['q']}**", f"  - Changes: {i['changes']}", f"  - Who answers: {i['who']}", f"  - Evidence: {i['evidence']}"]
    if not qs:
        L.append("None open. Everything the assessment needs from the client is answered, waiting, or an accepted assumption.")
    L.append("")
    L += ["## Waiting for the client", ""]
    ws = group(items, "client", "waiting")
    for i in ws:
        L += [f"- **{i['q']}** Client said: {one_line(i['answer'], 200)}", f"  - Changes: {i['changes']}", f"  - Evidence: {i['evidence']}"]
    if not ws:
        L.append("Nothing is waiting for the client.")
    L += ["", "## Not asked: we handle it ourselves", ""]
    for i in ours:
        L.append(f"- **{i['q']}** {i['evidence']} Done: {i['answer']}.")
    for i in items:
        if i["status"] == "closed" and i["group"] != "client" and not i["decision"]:
            L.append(f"- **{i['q']}** {one_line(i['answer'] or i['evidence'], 200)}")
    if not ours and not any(i["status"] == "closed" for i in items):
        L.append("Nothing to note here.")
    L += ["", "## Decisions for you", ""]
    dec = [i for i in items if i["decision"] and i["status"] != "closed"] + [i for i in items if i["decision"] and i["status"] == "closed"]
    L += [f"- **{i['q']}** Changes: {i['changes']} Evidence: {i['evidence']}" for i in dec] or ["No decisions open."]
    L += ["", "## Lower priority: for our own DevOps team", "", "Not for the client and not for the .NET team to chase. These come from the code and the server list and matter for network setup and supplier allow-lists.", ""]
    dv = group(items, "devops", "open") + group(items, "devops", "waiting")
    for i in dv:
        L += [f"- **{i['q']}**", f"  - Changes: {i['changes']}", f"  - Who answers: {i['who']}", f"  - Evidence: {i['evidence']}"]
    if not dv:
        L.append("Nothing open for DevOps.")
    dv_dev = group(items, "dev", "open")
    if dv_dev:
        L += ["", "## For the dev lead", ""]
        L += [f"- **{i['q']}** Changes: {i['changes']} Evidence: {i['evidence']}" for i in dv_dev if not i["decision"]]
    return "\n".join(L) + "\n"


def short_md(cfg, d, items, today):
    client = cfg.get("client") or "Client"
    L = [f"# {client} .NET apps: questions to ask (short list)", "", header(cfg, d, today),
         "", "Short version of the full list. Only what the .NET team needs answered.", ""]
    L += [f"## Ask {client} (client)", ""]
    cl = group(items, "client", "open")
    L += [f"- {i['q']} ({one_line(i['changes'], 120)})" for i in cl] or ["None open."]
    L += ["", "## Waiting for the client", ""]
    L += [f"- {i['q']} Client said: {one_line(i['answer'], 120)}" for i in group(items, "client", "waiting")] or ["Nothing."]
    L += ["", "## Decisions for you", ""]
    L += [f"- {i['q']}" for i in items if i["decision"]] or ["None."]
    L += ["", "## Lower priority: for our own DevOps team", ""]
    L += [f"- {i['q']}" for i in group(items, "devops", "open") + group(items, "devops", "waiting")] or ["Nothing open."]
    return "\n".join(L) + "\n"


def email_md(cfg, d, items, today):
    client = cfg.get("client") or "Client"
    contact = cfg.get("client_contact") or (cfg.get("intake") or {}).get("client_contact")
    qs = group(items, "client", "open") + group(items, "client", "waiting")
    L = [f"# {client} .NET apps: questions for the client email", "",
         f"DRAFT, {today}. Ready to send after you read it. Nothing is final until you say so.", "",
         f"**Subject:** {client} .NET assessment: {len(qs)} question{'s' if len(qs) != 1 else ''} for the build", "",
         f"Hello{' ' + contact if contact else ''},", "",
         "We are finishing the AWS assessment of the .NET applications. The points below need an answer from your side. Each one says what it changes in the plan.", ""]
    if qs:
        for n, i in enumerate(qs, 1):
            L += [f"{n}. **{i['q']}**", f"   {i['changes']}", ""]
    else:
        L += ["We have no open questions for you at the moment.", ""]
    L += ["Thank you. Please reply to this email or tell us who should answer.", "",
          (cfg.get("prepared_by") or "").strip() or "The assessment team"]
    return "\n".join(L) + "\n"


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Write the open questions, short list and client email from the assessment data.")
    ap.add_argument("--out", default=os.path.join(OUT, "documents"), help="folder to write into (default assessment/documents)")
    a = ap.parse_args()
    root, cfg = load_config()
    os.chdir(root)
    cfg["_root"] = root
    d = load_inputs(root)
    items, ours, answered = build_all(root, cfg, d)
    today = datetime.date.today().isoformat()
    base = slug(cfg.get("client"))
    out = a.out if os.path.isabs(a.out) else os.path.join(root, a.out)
    brand = bool((cfg.get("docx_template") or "").strip())
    files = {
        f"{base}-open-questions.md": full_md(cfg, d, items, ours, answered, today),
        f"{base}-open-questions-short.md": short_md(cfg, d, items, today),
        f"{base}-questions-for-client-email.md": email_md(cfg, d, items, today),
    }
    for name, md in files.items():
        hp = write_pair(os.path.join(out, name), md, brand=brand)
        print(f"wrote {os.path.join(out, name)} (+ {os.path.basename(hp)})")
    n_open = len(group(items, "client", "open"))
    print(f"{n_open} open client question(s), {len(group(items, 'client', 'waiting'))} waiting, {len(group(items, 'devops', 'open'))} for DevOps")


if __name__ == "__main__":
    main()
