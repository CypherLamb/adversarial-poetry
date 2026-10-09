"""adversarial-poetry.

A writer-only harness for generating adversarial-poetry artifacts with local
Ollama models, exposed three ways that share one generation service:

  * an MCP stdio server (``adversarial_poetry.server``),
  * an Ollama-orchestrated terminal MCP client (``adversarial_poetry.client``),
  * a deterministic CLI that does not rely on model tool calls
    (``adversarial_poetry.cli``).

The tool only *writes* poems to user-selected files. It never submits,
tests, or transmits generated artifacts anywhere. There is no cloud fallback.

Target platform: Unix-like systems (Kali Linux primary). Windows is out of
scope by design.
"""

__version__ = "1.0.0"
