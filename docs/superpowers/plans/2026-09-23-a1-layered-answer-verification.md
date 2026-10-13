# A1 Layered Answer Verification Implementation Plan

> **For agentic workers:** Implement in order with tests before each behavior change.

**Goal:** Make A1 answer scoring conservative, mathematical, and auditable.

**Architecture:** `verification.verify_answer(actual, expected, question_type)` returns a four-state private result. Existing `tools.evaluation` remains the harness entry point; rollout maps review results to a separate terminal state. Structured answers coexist with legacy strings.

**Tech Stack:** Python 3.13, unittest, SymPy 1.14, SQLite.

**Spec:** `docs/superpowers/specs/2026-09-23-a1-layered-answer-verification-design.md`

## Tasks

- [ ] Create `eduworld` and `requirements.txt` with SymPy; verify import.
- [ ] Write failing tests for choice, numeric, expression, interval, multipart and uncertain cases.
- [ ] Implement `verification/` normalization, typed dispatch and restricted SymPy conversion.
- [ ] Test `evaluate_submission()` compatibility and private review result; integrate verifier.
- [ ] Test and implement rollout `needs_review` status and summary counts.
- [ ] Migrate verified multi-part examples in `normalized/solutions.json` to versioned JSON.
- [ ] Document behavior, run full A1 suite and verify no reference data reaches model messages.

Each step is accepted only after its focused tests pass; no LLM Judge supplies final reward.
