# Contributing to mineru-runpod

Thanks for considering a contribution. This project is intentionally a thin wrapper — most of the actual document-parsing work happens upstream in [MinerU](https://github.com/opendatalab/MinerU). Please route your issue to the right place:

## What this repo is responsible for

- The RunPod serverless worker (`handler.py` and the `worker/` package) — the job envelope, the input schema (`worker/schema.py`), the MinerU call (`worker/parse.py`)
- What this worker declares to the harness: env prefix, input roots, output manifest (`worker/harness.py`)
- The Python client (`mineru_client/`)
- Deploy / destroy scripts
- The Dockerfile + dependency pinning

## What this repo is *not* responsible for

- **Parsing accuracy / quality** of MinerU's output → file at [opendatalab/MinerU](https://github.com/opendatalab/MinerU/issues).
- **Engine features MinerU doesn't offer, or has dropped** (an OCR language switch, a parsing mode of our own) → upstream too. This template mirrors MinerU's surface under MinerU's names and adds no engine behaviour; see "Mirror upstream MinerU" in [AGENTS.md](AGENTS.md).
- **Input transport, outbound target checks, response packaging, structured logging, the model-cache probe** → these come from [`runpod-doc-worker`](https://github.com/sergeyshmakov/runpod-doc-worker) ([docs](https://rdw.shmakov.tools)), the engine-agnostic harness extracted from this worker. A bug in how a URL is fetched or a tarball is built belongs there; a bug in *which* files go into it belongs here, in the manifest.
- **RunPod platform behaviour** (endpoint won't scale, FlashBoot misbehaves, cold start too long) → RunPod support.
- **vLLM / CUDA issues** → vLLM upstream.

If you're not sure, open an issue here and we'll redirect.

## Bug reports

Please include:
- The exact `deploy.py` command you ran (with secrets redacted)
- The `MineruClient.parse_document(...)` call (input shape, not the file contents itself)
- The full handler response — especially the `error` and `traceback` fields if `ok: false`
- The MinerU version reported in the response (`mineru_version`) and the tier that ran (`debug.tier`)
- The RunPod endpoint id and approximate timestamp so we can correlate with platform logs if needed

## Pull requests

- Keep PRs small and focused. Independent bug fix + refactor = two PRs.
- Run the test suite locally: `pip install -e ".[test]" && pytest -v`.
- New code paths need at least one test. CPU-only tests, please — CI doesn't have a GPU.
- Don't break the job contract (documented in [`docs/content/docs/reference/api.mdx`](docs/content/docs/reference/api.mdx)) quietly. A contract break ships on a minor under the `contract:` type, an installability break under `compat:`; both lead the release notes. Don't add `!` or a `BREAKING CHANGE:` footer: that cuts a major, and the major is reserved for a MinerU major and is the owner's call. See [AGENTS.md](AGENTS.md).
- `CHANGELOG.md` is maintained by semantic-release — do **not** edit it by hand. Write a good commit message instead (see below).

## Commit message format — Conventional Commits

We use [Conventional Commits](https://www.conventionalcommits.org/) so version bumps and changelog entries are generated automatically.

```
type(optional-scope): short summary in present tense

optional body explaining the why, wrapped at ~80 cols

optional footer(s)
```

Types that **trigger a release**:

| Type | Bump | Example |
|---|---|---|
| `contract:` | minor, leads the notes under **Job Contract Changes** | `contract(schema): default transport to inline` |
| `compat:` | minor, leads the notes under **Compatibility Changes** | `compat(client): require Python 3.11` |
| `feat:` | minor | `feat(client): add streaming response support` |
| `fix:` | patch | `fix(handler): handle PDFs with empty page_range` |
| `perf:` | patch | `perf(handler): stream tarball instead of buffering` |
| `refactor:` | patch | `refactor(client): split parse_document into smaller helpers` |
| `revert:` | patch | `revert: revert "feat: streaming response"` |

Types that **do not** trigger a release:

| Type | Use for |
|---|---|
| `docs:` | doc-only changes (`docs(readme):` triggers a patch though) |
| `test:` | adding/refactoring tests |
| `build:` | Dockerfile, requirements.txt, dep bumps |
| `ci:` | GitHub Actions workflows |
| `chore:` | anything else (housekeeping) |
| `style:` | formatting only |

**Breaking changes** use `contract:` (a renamed or removed job field, a default that flips, a value that used to be accepted and now is not) or `compat:` (a raised Python floor, a removed import path), and say in the body what breaks and what to do instead:

```
contract(schema): default transport to inline

Jobs that omit transport now get an inline response instead of a
tarball. Send transport: "tarball_b64" to keep the archive.
```

A `!` in the title or a `BREAKING CHANGE:` footer publishes a **major** version with no further gate. The major is reserved for a new MinerU major, and only the owner decides one — see [AGENTS.md](AGENTS.md).

Commitlint runs on every PR — bad messages will be rejected. Locally you can preview with `npx commitlint --from HEAD~1 --to HEAD --verbose`.

## Stability guarantees

- The major version moves only with a MinerU major: 2.x runs MinerU 4.1, 1.x ran MinerU 3.4.
- The job input/output contract and the public `MineruClient` / `MineruApiClient` signatures can break on a minor, and only in a release whose notes lead with it, under **Job Contract Changes** or **Compatibility Changes**. Read those before upgrading a minor; see [Versioning](https://mineru.shmakov.tools/reference/versioning/).
- Anything prefixed `_` is private; expect it to change.

## Code style

No enforced formatter yet — just match the existing style. Type hints encouraged, not required.

## License

By contributing, you agree your contributions are licensed under the [MIT License](LICENSE) of this repo.
