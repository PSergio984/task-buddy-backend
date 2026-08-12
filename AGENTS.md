# AGENTS.md — Task Buddy Backend

## Standing quality gates (user-mandated)

Every time work reaches a "done" state — a phase/plan execution completes with a commit, a PR is created, or a branch is finished — invoke ALL of the following before declaring done:

1. **SonarCloud scan** — run SonarCloud analysis (sonar-scanner) on the branch and address or record findings (bugs, vulnerabilities, smells, coverage).
2. **CodeRabbit review** — invoke the CodeRabbit AI review (workspace skill: `.agents/skills/rabbit-code-review`) on the branch/PR and address or record findings.
3. **CI/CD check** — confirm GitHub Actions CI (`.github/workflows/python-app.yml`, `sonar-secrets.yml`) passes on the branch/PR; extend pipelines when needed.

This complements the two-axis `/code-review` skill (Standards + Spec), which runs BEFORE commit on uncommitted work.

Notes: sonar-scanner is not installed on the dev host; first SonarCloud run needs a `SONAR_TOKEN` (HITL). CodeRabbit needs the app installed on the repo.
