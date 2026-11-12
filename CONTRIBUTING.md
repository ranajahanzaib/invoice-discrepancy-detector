# Contributing

Contributions that improve reliable, explainable invoice reconciliation are welcome. For larger changes, open an issue first to discuss scope and compatibility.

## Development setup

Use Python 3.11 or newer and Node.js 20 or newer. Follow the setup steps in the [README](README.md). Keep local databases, uploaded documents, credentials, and customer data out of commits.

## Changes

- Keep all monetary calculations in the backend and use `Decimal`.
- Preserve the distinction between missing data and a numeric zero.
- Keep validation deterministic; optional AI must never change financial outcomes.
- Add or update tests for behavior changes.
- Update user documentation when commands, API behavior, or limitations change.

Before submitting, run the available checks:

```bash
ruff check backend
python -m compileall -q backend
cd frontend && pnpm run build
```

Pull requests should describe the user-visible change, its validation, and any known limitations. Do not include credentials, real invoices, or other sensitive data in code, fixtures, screenshots, or issue reports.
