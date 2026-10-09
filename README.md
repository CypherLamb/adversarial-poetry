# adversarial-poetry

A **writer-only** harness for generating adversarial-poetry artifacts with
local [Ollama](https://ollama.com) models, for local red-team / LLM-safety
research on Unix. It never submits, tests, scores, or transmits what it writes,
and has no cloud fallback.

It exposes one generation service three ways:

1. a **Python MCP server** over stdio (`adversarial-poetry-server`);
2. an **Ollama-orchestrated terminal MCP client** that drives the server via
   model tool calls (`adversarial-poetry-client`);
3. a **deterministic CLI** that uses the same service directly, without any
   model tool calls (`adversarial-poetry`).

The whole workflow runs locally, with no Claude or other cloud service at
runtime:

```
terminal client  ->  MCP server  ->  local Ollama writer models  ->  your poem file
```

> **Platform.** Target is Unix-like systems, **Kali Linux primary**, other
> Linux secondary, macOS best-effort. **Windows is out of scope** and
> intentionally unsupported (the writer relies on Unix file semantics:
> `O_NOFOLLOW`, `O_EXCL`, `flock`, owner-only modes).

> **Scope of the tool.** It is a *writer*. Subject matter comes entirely from
> your brief; the tool supplies poetic structure and local generation. There is
> no automated challenge submission or target testing of any kind.

---

## 1. Requirements

- A Unix-like OS (Kali Linux assumed below).
- Python 3.11 or newer.
- A running local Ollama with at least one model pulled. **Nothing is assumed
  to be installed** — this project never installs Ollama, downloads models, or
  changes its service configuration.

Everything runs as an **ordinary unprivileged user**. No root, no `sudo pip`,
no `--break-system-packages`, and nothing installed into Kali's system Python.

---

## 2. Install on Kali Linux

All commands run as a normal user from the project directory.

### 2.1 Check Python

```sh
python3 --version        # expect 3.11+
```

### 2.2 Install venv prerequisites *if missing* (Kali/Debian-specific)

Only if the next step complains that `venv`/`ensurepip` is unavailable. This is
the one place that needs apt; run it yourself — the project never performs
privileged installs:

```sh
sudo apt update
sudo apt install -y python3-venv python3-pip
```

### 2.3 Create and activate a project-local virtual environment

```sh
cd /path/to/adversarial-poetry
python3 -m venv .venv
. .venv/bin/activate
```

### 2.4 Install the project into that environment

```sh
python -m pip install --upgrade pip
python -m pip install -e .
# For the test suite as well:
python -m pip install -e '.[dev]'
```

This provides three entry points on your `PATH` (inside the venv):
`adversarial-poetry`, `adversarial-poetry-server`, `adversarial-poetry-client`.

### 2.5 Check connectivity to the configured Ollama endpoint

Ollama stays bound to its configured local endpoint; this project does not
change firewall rules, network bindings, or service settings.

```sh
# Is the daemon up? (start it in another terminal with: ollama serve)
curl -sS http://127.0.0.1:11434/api/tags
```

### 2.6 List installed models

```sh
ollama list
# or, through this tool, once configured:
adversarial-poetry models
```

If you have no models yet, pull one yourself (this tool will not):

```sh
ollama pull llama3.1
```

### 2.7 Configure allowed output roots

Write a starter config, then edit it:

```sh
adversarial-poetry init-config
# -> ~/.config/adversarial-poetry/config.toml   (never overwrites an existing one)
```

Create your output directory and point the config at it. Use a normal
home-directory path (not `/root`):

```sh
mkdir -p ~/Poetry/arena-drafts
```

Edit `~/.config/adversarial-poetry/config.toml`:

```toml
[ollama]
endpoint = "http://127.0.0.1:11434"
request_timeout = 120.0

[generation]
writer_models = ["llama3.1"]     # only what you have actually pulled
default_form = "free_verse"
temperature = 0.8
# seed = 1234                     # set for repeatable batches

[output]
allowed_roots = ["~/Poetry/arena-drafts"]
```

### 2.8 Launch the MCP server

Normally the terminal client launches this for you, but you can run it directly:

```sh
adversarial-poetry-server
```

Protocol (JSON-RPC) goes to **stdout**; all logs/diagnostics go to **stderr**.

### 2.9 Run the Ollama-based terminal client

```sh
adversarial-poetry-client --model llama3.1
```

It launches the server as a subprocess (explicit executable + argument list,
no shell), exposes the writer tools to the model, and runs an interactive
prompt. `Ctrl+C`, `Ctrl+D`, or `/quit` exit cleanly and tear the server down.

### 2.10 Generate and append poems with the deterministic CLI

```sh
# Append (default) three villanelles to a file inside an allowed root:
adversarial-poetry generate "the lighthouse keeper's last winter" \
    --form villanelle --count 3 --model llama3.1 \
    --output ~/Poetry/arena-drafts/keeper.txt

# Exclusively create a new file (fails if it already exists):
adversarial-poetry generate "tide tables" -f haiku --create \
    -o ~/Poetry/arena-drafts/tides.txt

# Print to stdout without writing anything:
adversarial-poetry generate "a rusted key" -f sonnet --stdout
```

---

## 3. MCP client configuration (for an external MCP host)

If you want to register the server with a separate MCP host, use an **explicit
absolute path** to the installed server executable. Replace the placeholder
`/ABSOLUTE/PATH/TO` with your real venv path (e.g. the output of
`command -v adversarial-poetry-server` after activating the venv):

```json
{
  "mcpServers": {
    "adversarial-poetry": {
      "command": "/ABSOLUTE/PATH/TO/adversarial-poetry/.venv/bin/adversarial-poetry-server",
      "args": ["--config", "/ABSOLUTE/PATH/TO/home/.config/adversarial-poetry/config.toml"]
    }
  }
}
```

The only placeholder you must replace is `/ABSOLUTE/PATH/TO` (twice): the path
to your checkout's `.venv` and the path to your config file.

A copy of this example lives at [`examples/mcp-client.json`](examples/mcp-client.json).

---

## 4. Path and output rules

Output paths are resolved predictably (see `adversarial_poetry/paths.py`):

- A leading `~` / `~user` is expanded. **Environment variables are not
  expanded** — `$HOME` is a literal component.
- **Absolute** paths are used as-is.
- **Relative** paths resolve against the **first configured allowed output
  root**, never against the process working directory. MCP behavior therefore
  never depends on an unexplained CWD.
- The result is lexically normalised; obvious `..` traversal is detectable.

Writes are then confined and hardened at open time (`safeio.py`):

- The target must sit inside an allowed root, verified by walking the real
  directories from the root down with `O_NOFOLLOW` (a symlink anywhere on the
  path is refused, not followed).
- The destination is opened `O_NOFOLLOW`: an existing output file that is a
  symlink is refused.
- Only **regular files** are accepted — FIFOs, devices, sockets, directories
  are rejected.
- New files are created mode `0o600`; application-owned config/state/cache
  directories mode `0o700`. Existing files/directories are never `chmod`-ed.
- **Nothing is ever silently overwritten.** `--create` uses `O_EXCL`; append is
  the only way to add to an existing file.

### Append locking (and its honest limits)

Append mode takes an exclusive **advisory** `flock` for the whole batch, so
poems from separate requests/processes cannot interleave, and `fsync`s before
releasing. Advisory locking only serialises **cooperating** writers — an
unrelated program that writes without `flock` is *not* held back. This is **not
crash-atomic**: a crash mid-append can leave a partial batch. We do not claim
otherwise.

---

## 5. Exit codes

| Code | Meaning                                             |
|-----:|-----------------------------------------------------|
| 0    | success                                             |
| 2    | invalid arguments / path-policy violation           |
| 3    | configuration failure                               |
| 4    | connection failure (Ollama unreachable)             |
| 5    | partial generation failure                          |
| 130  | interrupted (SIGINT)                                |
| 143  | terminated (SIGTERM)                                |

CLI output is script-friendly: results on stdout, diagnostics/progress on
stderr.

---

## 6. Running the tests

The default suite needs **no root, no GPU, no live Ollama, and no network**;
it uses temporary directories and a fake Ollama client. It is Unix-focused —
the filesystem-security and transport tests require Linux/Unix semantics.

```sh
. .venv/bin/activate
python -m pytest
```

Covered: paths with spaces/Unicode, relative resolution, tilde expansion,
symlinked parents and destinations, writes outside roots, non-regular targets,
exclusive creation, default `0o600` permissions, concurrent cross-process
append locking, cancellation, subprocess launch/cleanup, and stdout/stderr
transport separation.

---

## 7. License

MIT. See `LICENSE`.
