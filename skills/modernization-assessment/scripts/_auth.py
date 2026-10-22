"""Authentication and authorization per application: how users and calling systems prove who they are today, how access
is decided, what that becomes on ASP.NET Core and which AWS service takes it over. Built from the auth-related findings
(rules.json) and the wording in data/auth.json; nothing is rescanned.

    rows = build(findings, applications, project_model)

Each row: the application, who signs in (people through a web UI, Windows accounts, other systems, an existing identity
provider, or nothing found), every mechanism with its evidence and finding references, the recommended AWS target with
the reason, ordered steps for the .NET developer, and the questions for the client.
"""
from _common import data

ORDER = {"authn": 0, "secrets": 1, "authz": 2, "session": 3}


def build(findings, apps, projects=None):
    g = data("auth.json")
    mech, rec = g["mechanisms"], g["recommendations"]
    group_of = {(p["repo"], p["path"]): p["group"] for p in (projects or {}).get("projects", [])}
    rows = []
    for a in apps:
        # the application's own project only: a referenced project's findings belong to that project's own row
        fs = [f for f in findings if a["id"] in f.get("apps", []) and f["rule"] in mech and f.get("project") in (a.get("entry"), "(repository)")]
        by = {}
        for f in fs:
            m = by.setdefault(f["rule"], {"rule": f["rule"], **{k: mech[f["rule"]][k] for k in ("area", "label", "today", "core", "aws")},
                                          "severity": f["severity"], "refs": [], "where": [], "count": 0})
            m["refs"].append(f.get("ref", ""))
            m["count"] += f.get("occurrences", 1)
            m["where"] += [f"{e.get('file')}:{e.get('line')}" for e in f.get("evidence", [])[:3]]
        ms = sorted(by.values(), key=lambda m: (ORDER.get(m["area"], 9), m["label"]))
        rules = set(by)
        group = group_of.get((a["repo"], a.get("entry")), "")
        own = rules & {"AUTH-CUSTOM-LOGIN", "AUTH-DB-CREDENTIAL-CHECK", "AUTH-FIXED-HEADER-SECRET", "AUTH-API-KEY", "AUTH-FORMS-MEMBERSHIP", "AUTH-BASIC", "AUTH-JWT", "AUTH-OWIN-OAUTH"}
        if "AUTH-WINDOWS" in by and (own or "AUTH-CONFIG-RULES" not in rules):
            # <authentication mode="Windows" /> is the template default: without <deny users="?"> IIS usually keeps anonymous access on
            by["AUTH-WINDOWS"]["today"] += (" web.config sets Windows mode but no <authorization> rule requires a signed-in user, so IIS anonymous access"
                                              " is probably on: confirm the IIS site settings.")
        if (rules & {"AUTH-IMPERSONATION"}) or ("AUTH-WINDOWS" in rules and not own and "AUTH-CONFIG-RULES" in rules):
            kind = "windows"
        elif rules & {"AUTH-WSFED", "AUTH-EXTERNAL-IDP", "AUTH-ASPNETCORE"}:
            kind = "existing-idp"
        elif group in ("webforms", "ui", "desktop") or rules & {"AUTH-CUSTOM-LOGIN", "AUTH-FORMS-MEMBERSHIP", "AUTH-IDENTITY2"}:
            kind = "user-facing"
        elif any(m["area"] == "authn" for m in ms):
            kind = "machine"
        else:
            kind = "none" if group not in ("api", "service", "job", "modern") or not ms else "machine"
        if kind == "user-facing" and not any(m["area"] == "authn" for m in ms):
            kind = "none"
        r = rec[kind]
        steps = []
        for m in ms:
            if m["area"] != "authn":
                continue
            if m["rule"] == "AUTH-WINDOWS" and own:
                steps.append("Windows mode in web.config: confirm in IIS whether anonymous access is on; if it is, drop Windows auth in the port.")
            else:
                steps.append(f"{m['label']}: {m['core'].rstrip('.')}.")
        if any(m["rule"] == "AUTH-REVERSIBLE-PASSWORD" for m in ms):
            steps.append("Stop storing reversible passwords: hash them (rehash at next sign-in) or move the users to Amazon Cognito.")
        if any(m["area"] == "secrets" for m in ms) or any(m["rule"] in ("AUTH-FIXED-HEADER-SECRET", "AUTH-API-KEY", "AUTH-JWT", "AUTH-BASIC") for m in ms):
            steps.append("Move every key, password and token the auth depends on to AWS Secrets Manager (or KMS for signing keys) and read them through configuration.")
        if any(m["area"] == "authz" for m in ms):
            steps.append("Port the access rules as ASP.NET Core authorization policies / handlers: " + ", ".join(m["label"].lower() for m in ms if m["area"] == "authz") + ".")
        if any(m["area"] == "session" for m in ms):
            steps.append("Move session to Amazon ElastiCache (or drop it in favour of claims) so any container can serve any request.")
        if ms:
            steps.append("Write tests before the port: a signed-in and a signed-out request (and a wrong-role request) for every protected page or message, run again after the port.")
        steps.append(f"On AWS: {r['aws']}.")
        qs = sorted({f["question"] for f in fs if f.get("question") and not (f["rule"] == "AUTH-WINDOWS" and own)})
        if kind == "none":
            qs.append(f"What protects {a['name']} today (network rules, IIS settings, a gateway in front)?")
        rows.append({"id": a["id"], "app": a["name"], "repo": a["repo"], "type": a.get("type", ""), "kind": kind, "who": r["title"],
                     "mechanisms": ms, "authn": [m["label"] for m in ms if m["area"] == "authn"], "authz": [m["label"] for m in ms if m["area"] == "authz"],
                     "secrets": [m["label"] for m in ms if m["area"] in ("secrets", "session")],
                     "aws": r["aws"], "core": r["core"], "why": r["why"], "steps": steps, "questions": qs,
                     "worst": min((m["severity"] for m in ms), key=lambda s: ["Blocker", "High", "Medium", "Low", "Info"].index(s), default="Info")})
    return rows
