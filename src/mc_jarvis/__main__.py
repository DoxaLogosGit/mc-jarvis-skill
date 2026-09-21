"""`python -m mc_jarvis` - the same entry point as the `mc-jarvis` script.

Without this, the package runs only through the console script a wheel
install creates, so a copy of the source sitting in a skill folder could
be imported but not run. `python -m mc_jarvis.cli` did not help either:
`cli.py` has no `__main__` guard, so it imported cleanly and exited 0
having done nothing, which reads exactly like a command with no output.
"""
from .cli import main

raise SystemExit(main())
