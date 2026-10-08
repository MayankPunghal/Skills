<!-- guide: Contents (stripped from the client report)
## Contents
- 1. Executive summary
- 2. Scope and method
- 3. Applications and what must change
- 4. Network, integrations and dependencies
- 5. Findings that affect the move
- 6. Databases
- 7. Effort estimate and timeline
- 8. Future options (not in the estimate)
- 9. Risks, assumptions and open questions
- 10. Testing and cut-over
- 11. Appendices
-->

<!-- guide: Lift-and-shift report: used by build_report.py when assessment.json assessment_type is "lift-and-shift" (set by
intake.py). Every server moves to Amazon EC2 with the same operating system; the report leads with what must change for
that move (network addresses, DNS, mail, file shares, identity, licences, jobs) and keeps Linux / .NET modernization
findings as future work in section 8. Same placeholders as report-template.md. -->
# {{meta:client}} — {{meta:engagement}}

| | |
|---|---|
| Prepared by | {{meta:prepared_by}} |
| Prepared for | {{meta:client}} |
| Date / version | {{meta:date}} / {{meta:version}} |
| Target platform | Amazon EC2, same operating systems as today (lift-and-shift) |
| Current hosting (as stated) | {{meta:hosting}} |
| Compliance context (as stated) | {{meta:compliance}} |
| Classification | Confidential — contains architecture and security findings |

## 1. Executive summary

{{narrative:executive-summary}}

### 1.1 At a glance

{{block:headline}}

### 1.2 What could stop or break the move

{{block:key-risks}}

## 2. Scope and method

### 2.1 What the client asked for

{{block:intake}}

### 2.2 What was assessed

{{block:scope}}

### 2.3 How

{{block:method}}

Every finding in this report cites evidence (file and line, package and version, or configuration key). Severity: **Blocker** stops the application working after the move until it is changed; **High** must be changed or decided before cut-over; **Medium** needs a change that is contained; **Low** is clean-up; **Info** is a fact recorded for planning. Confidence: **Confirmed** (seen in code), **Likely** (pattern seen, context not fully traced), **Needs verification** (depends on servers, network or partners we could not see).

### 2.4 What could not be assessed

{{block:not-assessed}}

## 3. Applications and what must change

{{block:landing-summary}}

{{narrative:application-plans}}

Inventory detail (types, frameworks, size) is in Appendix A2.

## 4. Network, integrations and dependencies

{{narrative:architecture}}

### 4.1 Third-party services, on-premises systems and SDKs

{{block:third-party}}

### 4.2 Network allow-list and all upstream and downstream systems

{{block:network}}

{{block:dependencies}}

### 4.3 Scheduled and background jobs

{{block:jobs}}

### 4.4 Application and dependency map

{{block:architecture-diagram}}

### 4.5 Project interdependencies (what must move together)

{{block:project-deps}}

{{narrative:dependencies}}

## 5. Findings that affect the move

{{block:findings-in-scope}}

## 6. Databases

{{block:database}}

{{narrative:database}}

## 7. Effort estimate and timeline

### 7.1 Coding and configuration effort by work package

{{block:estimate}}

### 7.2 Scenario comparison

{{block:scenarios}}

### 7.3 Whole estate (repositories estimated from the assessed sample)

{{block:estate-extrapolation}}

### 7.4 Timeline and sprint plan

{{block:timeline}}

{{block:sprints}}

### 7.5 Licensing and cost implications

{{block:cost}}

{{narrative:cost}}

### 7.6 Estimate assumptions and method

{{block:assumptions}}

{{block:methodology}}

## 8. Future options (not in the estimate)

### 8.1 Replacing servers with AWS managed services

{{block:aws-native}}

### 8.2 Linux and .NET modernization findings, for later

{{block:findings-future}}

## 9. Risks, assumptions and open questions

### 9.1 Risks

{{block:risks}}

{{narrative:risks-and-questions}}

### 9.2 Open questions for {{meta:client}}

{{block:open-questions}}

## 10. Testing and cut-over

### 10.1 Current automated tests

{{block:testing}}

### 10.2 Parallel development

{{block:merge}}

{{narrative:testing-and-merge}}

## 11. Appendices

### A1. Packages

{{block:appendix-packages}}

### A2. Applications and projects

{{block:inventory}}

{{block:appendix-projects}}

### A3. Raw scan outputs

{{block:appendix-raw}}

### A4. Sources

{{block:appendix-sources}}
