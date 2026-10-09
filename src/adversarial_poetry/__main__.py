"""Allow ``python -m adversarial_poetry`` to invoke the deterministic CLI."""

from adversarial_poetry.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
