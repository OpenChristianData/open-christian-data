# Open Christian Data

Public dataset repo. Use American English only. All scripts use `py -3`, not `python`.

- Branch: `main`
- Validate: `py -3 build/validate.py --all`
- Pre-commit hook blocks identifying strings — identity protection, do not bypass
- Non-obvious kind/tradition classification rationale: `build/CLASSIFICATION_LOG.md`
- After multi-edit sessions on any `.py` file: `py -3 -m py_compile <file>` before declaring done
- Standard Ebooks parser: `--list-files` to verify filtered input before extraction; `expected_count` in source config asserts correct count at runtime
- Session history and planning docs: see `.claude/CLAUDE.md` (local, gitignored)
