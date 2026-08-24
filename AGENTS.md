# Working in this repo

`mineru-runpod` is a published RunPod Hub serverless template. `main` is
released automatically: every push runs semantic-release, which reads the commit
titles, decides the next version, tags it, and publishes a GitHub Release. There
is no separate "release" step a human performs.

Read that again before you commit anything, because it is the fact behind the
rule below.

## Never mark a change breaking on your own

**Do not put `!` in a commit title, and do not write a `BREAKING CHANGE:` footer,
without explicit approval from the human you are working with.** Ask first, in
plain words, and let them decide.

A `!` is not a note for readers. It is an instruction to cut a **major version**
and publish it, with no further gate. An agent that adds one has decided the
version number and shipped it.

This is written here because it happened here. On 2026-08-24 a per-job SSRF
hardening on `server_url` was committed as `fix(schema)!:` — it did reverse
behaviour that was documented and tested, so the marker was defensible as a
*proposal*. It reached `main` and released **2.0.0**: a major version, for four
bug fixes and one hardening change. Reversing it meant deleting a published
Release and tag and force-pushing `main` back to 1.10.1. The owner's verdict:
"you released 2.0 version just because of some nit bug fixes we decided to make."

So when a change might break a consumer — a renamed or removed job field, a
default that flips, a value that used to be accepted and now is not, a job that
used to succeed and now fails validation — **stop and ask**. Describe what breaks
and for whom, then offer the alternatives:

- ship it as breaking, and let the major version happen deliberately;
- put the new behaviour behind an opt-in env flag so no existing job breaks;
- drop it.

Whether a change is worth a major version is the owner's call every time, never
the agent's. The safe default when unsure is the opt-in flag — for the case
above, `MINERU_ALLOW_LOCAL_FETCH` already existed, so the whole break was
avoidable.

## Never replay a PR branch onto main

The same day, a commitlint `subject-case` failure needed one commit message
reworded on an open PR. The five commits were cherry-picked onto `origin/main`
and force-pushed. That put them in main's ancestry, semantic-release fired 31
seconds later, and GitHub auto-closed the PR because its commits were already in
the base branch. The review was bypassed and the release above went out.

To rebuild or reword a PR branch, replay onto the branch's **own base commit**,
never onto `origin/main`. Before force-pushing, check all three:

```bash
git merge-base --is-ancestor <new-head> origin/main   # must FAIL
git merge-base origin/main <new-head>                 # must be the original fork point
git diff <old-head> <new-head>                        # must be empty
```

`git diff` being empty does not make a force-push safe. It says the content is
unchanged; it says nothing about where the commits now sit. Making a PR's commits
reachable from `main` is a merge whatever it is called — and here a merge is a
release.

## Commit format

Conventional Commits, enforced by commitlint in CI. Two rules that fail builds
and are easy to trip:

- `subject-case` rejects a subject starting with a capitalised token, so
  `fix(telemetry): OTel log export dropped …` fails. Reword rather than
  capitalise mid-sentence.
- `body-max-line-length` warns above 120 characters, so **commit bodies stay
  hard-wrapped** — unlike PR descriptions and Markdown, which do not.

## Before you finish

- `pytest tests/ -v` — the suite runs without a GPU and without `mineru`.
- If you changed the job contract, update `docs/content/docs/reference/api.mdx`.
- If you added an operator env var, add it wherever the env-var tests enumerate
  them; they fail in both directions until the lists agree.
- `npm run build`, `validate:links` and `validate:routes` in `docs/` when docs
  changed.
