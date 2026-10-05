# Evaluations for skill-publisher

## Contents

- [Prompts](#prompts)

## Prompts

### Bare invocation
Prompt: `/skill-publisher`
Should trigger: yes
Done looks like: exactly one question (which skill folder or zip) and a one-line description of what happens next; no files touched.

### Publish a folder
Prompt: "Publish the skill in C:/work/my-skill to my repo"
Should trigger: yes
First file Claude should open: `scripts/publish_skill.py prepare`
Done looks like: staged copy refactored, `check` reports `"ready": true`, pushed to the private repo unless the user said shareable, installed locally.

### Change an existing skill by name
Prompt: "/skill-publisher ytstudio: add a shorts-first mode"
Should trigger: yes
Done looks like: `prepare ytstudio` stages the repo copy, the change is made additively, nothing from the repo version is dropped.

### Should not trigger
Prompt: "Write me a new skill from scratch for summarising meetings"
Should trigger: no (skill-creator-plus or similar fits better; publish afterwards)

## Baseline log

| Date | Model | With skill? | Result |
| --- | --- | --- | --- |
