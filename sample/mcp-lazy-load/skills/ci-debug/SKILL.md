---
name: ci-debug
description: Debug a failing CI pipeline. Use when asked why CI is failing, to check workflow logs, or to rerun failed jobs.
allowed-tools:
  - Read
  - Bash(git:*)
  - mcp__github__get_workflow
  - mcp__github__get_workflow_log
  - mcp__github__rerun_workflow
---

# CI Debug Skill

Fetch workflow status, read logs, and rerun failed jobs.
