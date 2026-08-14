## Summary

Describe what changed and why.

## Related issue

Link the issue, or explain why this focused change does not need one.

## Verification

List commands and manual checks performed. Include the platform, Python
version, whether Ecowitt hardware was available, and any behavior that remains
unverified.

## Checklist

- [ ] I kept the change focused and avoided unrelated reformatting.
- [ ] I added or updated focused tests when behavior changed.
- [ ] `python -m pytest -q -W error` passes.
- [ ] Critical Ruff checks pass.
- [ ] I updated documentation when public behavior or configuration changed.
- [ ] I did not commit credentials, live settings, precise coordinates, private logs, or weather databases.
- [ ] I preserved settings, database, gateway, and normalized-metric compatibility.
- [ ] I updated `caelus/__init__.py` when code content changed.
