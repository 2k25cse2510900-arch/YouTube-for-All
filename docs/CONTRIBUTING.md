# Contributing to YouTube-for-All

Thank you for your interest in contributing to `YouTube-for-All`. This document outlines the development workflow, coding standards, and guidelines for submitting contributions.

---

## Development Environment Setup

1. **Fork and Clone**:
   Fork the repository to your GitHub account and clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/YouTube-for-All.git
   cd YouTube-for-All
   ```

2. **Virtual Environment**:
   Create a dedicated Python 3.10+ virtual environment:
   ```bash
   python -m venv .venv

   # Activate on Windows:
   .venv\Scripts\activate

   # Activate on Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   Install runtime and development packages in editable mode:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Verify System Tools**:
   Ensure `ffmpeg` and `ffprobe` are installed and reachable on your system `PATH`:
   ```bash
   ffmpeg -version
   ffprobe -version
   ```

---

## Coding Conventions

* **Code Style**: Follow PEP 8 guidelines across all Python modules.
* **Typing**: Use standard Python type annotations (`typing` or built-in generics) for function signatures and data structures.
* **Architecture**: Respect the modular structure. Core business logic belongs in `src/`, while top-level domain packages (`image_generation/`, `voice_and_audio/`, etc.) serve as facades. Do not introduce circular dependencies between engine components.
* **Logging**: Use standard logging through `src.common.logger.setup_logger`. Avoid unstructured `print()` calls in library code.
* **Error Handling**: Raise descriptive, typed exceptions. Do not silently catch exceptions without logging diagnostic details.

---

## Testing Guidelines

* **Run Existing Tests**:
  Before making changes or opening a pull request, run the full test suite to verify baseline functionality:
  ```bash
  pytest tests --tb=short
  ```

* **Write Tests for New Features**:
  All new functionality or bug fixes must include corresponding tests under the `tests/` directory.

* **Mock External Services**:
  Do not write tests that require live external network calls, paid cloud API credits, or external service accounts. Use unit test mocks or offline test providers (such as `mock_pillow` for images and mock TTS handlers) to keep tests fast, repeatable, and cost-free.

---

## Pull Request Process

1. **Create a Feature Branch**:
   Create a descriptive branch for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Commit Guidelines**:
   Write clear, concise commit messages summarizing the technical change. Group related changes into logical commits.

3. **Verify Locally**:
   Ensure all tests pass and no unintended files are staged:
   ```bash
   pytest tests --tb=short
   git status
   ```

4. **Submit PR**:
   Push your branch to your fork and submit a Pull Request against the `main` branch. Provide a clear description of the problem solved, changes made, and test coverage added.

---

## Security & Asset Protection Policy

To maintain repository security and respect intellectual property rights, all contributors must observe these strict constraints:

* **Zero Credentials**: Never commit `.env` files, API keys, OAuth tokens (`token.json`), client secrets (`client_secret.json`), or other private credentials.
* **No Proprietary Production Media**: Do not commit rendered production video files, full-length audio tracks, private episode scripts, or proprietary datasets.
* **Unlicensed Assets**: Do not commit copyrighted artwork, music, or media without verifiable open-source or creative commons licensing documentation.
