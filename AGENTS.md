# Repository Guidelines

## Project Structure & Module Organization

- `dailycheckin/` contains the Python package. `main.py` orchestrates tasks, `configs.py` handles configuration, and `utils/message.py` sends notifications.
- Each service lives in `dailycheckin/<service>/main.py` with an accompanying `__init__.py`. Implement a `CheckIn` subclass with a `name` and `main()` method; subclasses are discovered automatically.
- `docker/` contains deployment scripts and `config.template.json`.
- `docs/` hosts the Next.js/Nextra documentation: pages in `docs/pages/`, shared components in `docs/components/`, and images in `docs/pages/img/`.

## Build, Test, and Development Commands

Use Python 3.9 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . pre-commit build
```

- `make pre-commit`: run all configured hooks, including Ruff lint fixes and formatting. Review resulting edits.
- `python -m build --sdist --wheel --outdir dist/ .`: build release artifacts using the release workflow's command.
- `dailycheckin --help`: inspect CLI options.
- `dailycheckin --include FNNASCLUB`: run one configured service. This performs real account actions and may send notifications; configure credentials first.
- For documentation, run `npm install` inside `docs/`, then `npm run dev` for local development or `npm run export` to generate the static site.

## Coding Style & Naming Conventions

Use four-space indentation, Python 3.9-compatible syntax, and Ruff's 120-character formatting width. Follow `pyproject.toml` and `.pre-commit-config.yaml`. Prefer `snake_case` functions and variables, descriptive class names, and uppercase service configuration keys such as `FNNASCLUB`. Match neighboring service implementations and keep fixes scoped.

## Testing Guidelines

No automated test suite, dedicated test runner, or coverage threshold is currently configured. Run the hooks and record focused verification steps for the changed service. For new regression tests, use `tests/test_<service>.py`, mock HTTP requests and notifications, and document the execution command. Cover successful responses, expired credentials, malformed responses, and network failures where relevant. Treat live check-ins as integration checks with external side effects.

## Commit & Pull Request Guidelines

History mixes plain descriptive subjects with `feat`, `fix`, `docs`, `chore`, and scoped prefixes, sometimes with emoji. Prefer concise messages such as `fix(enshan): handle missing formhash`. Keep commits focused. PRs should describe affected services, behavior changes, configuration updates, and validation results; link relevant issues and include screenshots for documentation UI changes.

## Security & Configuration

Use `docker/config.template.json` as the starting point for the ignored local `config.json`. Never commit cookies, tokens, account details, or notification secrets. Update service documentation under `docs/pages/settings/` when configuration changes, and redact credentials from logs and screenshots.
