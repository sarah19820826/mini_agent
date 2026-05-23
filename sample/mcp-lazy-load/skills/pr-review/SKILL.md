---
name: pr-review
description: Review a GitHub pull request. Use when asked to review a PR, check PR changes, or summarize PR discussions.
allowed-tools:
  - Read
  - Write
  - Bash(git:*)
  - mcp__github__get_pr
  - mcp__github__get_pr_diff
  - mcp__github__get_pr_comments
  - mcp__github__get_workflow
  - mcp__github__get_file
---

# PR Review Skill

Read PR details, diff, comments, and CI status to generate a review summary.
