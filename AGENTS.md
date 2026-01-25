# 🤖 Development Guidelines

## **CODE**

### I. Codebase – One codebase tracked in revision control, many deploys

- 12 factor
- SOLID
- Only create one document per specification in `docs/` folder
- README with high-level architecture diagram (C4 / equivalent)
- Docstrings + type hints for all public functions

### II. Dependencies – Explicitly declare and isolate dependencies

### III. Config – Store config in environment variables

- No hardcoded config
- All config via environment variables
- Optional `.env` support for local dev
- Structured config object (e.g. `config.py`)
- Run as non-root user
- Authenticated and authorized HTTP requests

### IV. Backing services – Treat backing services as attached resources

### V. Build, release, run – Strict separation

- Installable Python package (`pyproject.toml`)
- Dockerfile defines ENTRYPOINT
- `docker-compose` for local/test environments
- CI runs lint, typecheck, tests
- **Linting & CI:**
  - Use `flake8` and `black` and sourcery lint every time Python code is updated
  - Align `scripts/run_tests.py` and `.github/workflows/ci.yml`
- Deployments include smoke tests
- Fast commit-to-prod cycle

### VI. Processes – Stateless execution

- Stateless processes only
- Expose `/healthz`
- Exit non-zero on fatal errors
- Handle SIGTERM gracefully
- No privileged execution
- Readiness probe defined
- Liveness probe only with clear justification

## **DEPLOY**

### VII. Port binding – Export services via port binding

### VIII. Concurrency – Scale via processes

### IX. Disposability – Fast startup, clean shutdown

### X. Dev/prod parity – Keep environments aligned

## **OPERATE**

### XI. Logs – Treat logs as event streams

- rich console logging

### XII. Admin processes – One-off tasks

### Clarification Rounds

- Ask numbered questions
- Each question has options A, B, C…
- Option A is recommended when applicable
- Include brief trade-offs per option
- Always include **Option X: Explain the options**

---

### When Context Is Missing

- Do not invent services, components, or names
- Ask for clarification instead of guessing

---

### Technology Decisions

- Stay within existing stack
- No new frameworks without discussion
- Check compliance docs before suggesting managed services

---

### Code Generation Rules

- Include type hints and docstrings
- **Testing:**
  - If creating a new test case, use the `tests/` folder and mirror the existing subfolder structure
  - Generate tests only for critical pure logic
- Use hexagonal architecture where complexity justifies it
- Apply retries and circuit breakers only to external calls

---

### XIII. AI Tooling

- Use Context7 MCP
- Use Playwright MCP

### XIV. Documentation Alignment

- Align arch diagrams: `docs/ADR/workspace.dsl`, `docs/LLD.md`
- Update `CHANGELOG.md` (SKIP "Release Notes")
- Future devs to `docs/SDD_backlog.md`

### XV. Testing & Linting

- Align `tests/` and `.github/workflows/ci.yml`
- Python: `ruff`, `flake8`, `black`
- JS/TS: `eslint`, `prettier`
- Align `scripts/run_tests.py`

### XVI. Database

- Clean install on DB mod (no migration)
- Align `scripts/seed_local_db.py` (clean install support)

### Output Requirements

- be extremley concise. sacrifice grammar for the sake of consision.
- Whenever you run a command in the terminal, pipe the output to a file, output.txt, that you can read from. Make sure to overwrite each time so that it doesn't grow too big.

<!-- OPENSPEC:START -->

# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:

- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:

- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->
