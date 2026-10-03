
<!-- guide: Contents (stripped from the client report)
- 1. Executive summary
- 2. Scope and method
- 3. Application inventory
- 4. Architecture and dependencies
- 5. Findings by category
- 6. Database assessment
- 7. Modernization plan per application
- 8. Effort estimate and timeline
- 9. Risks, assumptions and open questions
- 10. Testing, QA and merge strategy
- 11. Appendices
-->

<!-- guide: This file is the single place that defines the client report: section order, headings, fixed wording and
which generated blocks / narratives appear where. build_report.py fills it. To calibrate from your own sample reports,
edit headings, reorder sections, rename or drop blocks here - no code change is needed. Placeholders:
{{meta:client|prepared_by|engagement|date|target|compliance|hosting|version|repos}}, {{block:<name>}} (see build_report.py BLOCKS),
{{narrative:<name>}} (assessment/narrative/<name>.md). Comments that start with "guide:" are removed from the output. Tone and
wording rules: references/style-guide.md. -->
# {{meta:client}} — {{meta:engagement}}

| | |
|---|---|
| Prepared by | {{meta:prepared_by}} |
| Prepared for | {{meta:client}} |
| Date / version | {{meta:date}} / {{meta:version}} |
| Target platform | {{meta:target}} on Linux, Amazon Web Services |
| Current hosting (as stated) | {{meta:hosting}} |
| Compliance context (as stated) | {{meta:compliance}} |
| Classification | Confidential — contains architecture and security findings |

## 1. Executive summary

{{narrative:executive-summary}}

### 1.1 At a glance

{{block:headline}}

### 1.2 Key risks

{{block:key-risks}}

## 2. Scope and method

### 2.1 What was assessed

{{block:scope}}

### 2.2 How

{{block:method}}

Every finding in this report cites evidence (file and line, package and version, or configuration key). Severity: **Blocker** prevents running on Linux / modern .NET without replacing a technology; **High** needs code or design change before go-live; **Medium** needs change but is contained; **Low** is clean-up or hardening; **Info** is a fact recorded for planning. Confidence: **Confirmed** (seen in code), **Likely** (pattern seen, context not fully traced), **Needs verification** (depends on runtime or infrastructure we could not see).

### 2.3 What could not be assessed

{{block:not-assessed}}

## 3. Application inventory

{{block:inventory}}

Project-level detail (frameworks, project format, support status) is in Appendix A2.

### 3.1 Linux readiness by application

{{block:linux-readiness}}

### 3.2 What breaks on Linux

{{block:linux-issues}}

## 4. Architecture and dependencies

{{narrative:architecture}}

### 4.1 Application and dependency map

{{block:architecture-diagram}}

### 4.2 Code structure (from the code graph)

{{block:graph-insights}}

### 4.3 Third-party services, on-premises systems and SDKs

{{block:third-party}}

### 4.4 All upstream and downstream systems

{{block:dependencies}}

## 5. Findings by category

{{block:findings-summary}}

{{block:findings-by-category}}

## 6. Database assessment

{{block:database}}

### 6.1 Database inventory and PostgreSQL / dual-database effort

{{block:db-inventory}}

{{narrative:database}}

## 7. Modernization plan per application

{{narrative:application-plans}}

### 7.1 Shared libraries and hybrid path

{{block:hybrid}}

### 7.2 Application plans

{{block:app-plans}}

## 8. Effort estimate and timeline

### 8.1 Effort by work package (hours and person-days)

{{block:estimate}}

### 8.2 Scenario comparison (hosting and database options)

{{block:scenarios}}

### 8.3 Factors applied

{{block:multipliers}}

### 8.4 Phased timeline

{{block:timeline}}

### 8.5 Licensing and cost implications

{{block:cost}}

{{narrative:cost}}

### 8.6 Estimate assumptions

{{block:assumptions}}

## 9. Risks, assumptions and open questions

### 9.1 Risks

{{block:risks}}

{{narrative:risks-and-questions}}

### 9.2 Open questions for {{meta:client}}

{{block:open-questions}}

## 10. Testing, QA and merge strategy

### 10.1 Current automated tests

{{block:testing}}

### 10.2 Parallel development

{{block:merge}}

{{narrative:testing-and-merge}}

## 11. Appendices

### A1. Packages by compatibility group

{{block:package-groups}}

Full package inventory:

{{block:appendix-packages}}

### A2. Projects

{{block:appendix-projects}}

### A3. Windows-only and legacy API usage (all occurrences captured)

{{block:appendix-winapi}}

### A4. Raw scan outputs

{{block:appendix-raw}}

### A5. Sources

{{block:appendix-sources}}
