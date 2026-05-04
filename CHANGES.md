# Update Report — Exam Grading Agent
**Author:** Sanket Pai  
**Date:** May 2026  
**Scope:** All changes made from the original repository (`darrendariustan/Exam-Grading-Agent`) to the forked version (`SanketPai0518/Exam-Grading-Agent`)

---

## Overview

The original codebase was a working multi-agent exam grading system that used OpenAI's API directly via a personal API key. The primary goal of this update was to migrate the entire system to use the company's Azure OpenAI subscription, eliminating the need for personal API spending. Alongside this migration, several bugs were discovered and fixed, and the user-facing UI was improved.

---

## 1. Azure OpenAI Migration

### What changed
Every file that made API calls was updated to use `AzureOpenAI` instead of the plain `openai` module. This affected 5 files:

- `narrative-agent/exam_grader_agents.py`
- `technical-agent/tech_grading_agent.py`
- `vc-pitch-agent/vc_grader_agent.py`
- `vc-pitch-agent/vc_grader.py`
- `multi-agent/agent_orchestrator.py`

### The change in every file

**Before (all files):**
```python
import openai
openai.api_key = os.getenv("OPENAI_API_KEY")
```

**After (all files):**
```python
from openai import AzureOpenAI
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-06-01",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
```

### Why
OpenAI's API only requires a single key and sends traffic to OpenAI's servers directly. Azure OpenAI requires three things: an API key, a resource endpoint URL (the address of the company's specific Azure resource), and an API version string (Azure versions its API to guarantee stable behaviour). All three values are loaded from environment variables set in the Azure web app and a local `.env` file, meaning no credentials are ever hardcoded.

### Model name changes
Azure requires model names to match the deployment name created in Azure Foundry, not OpenAI's internal model identifiers.

| File | Before | After | Reason |
|---|---|---|---|
| `narrative-agent/exam_grader_agents.py` | `gpt-4-0613` | `gpt-4o` | `gpt-4-0613` is retired and unavailable on Azure |
| `technical-agent/tech_grading_agent.py` | `gpt-4-0125-preview` | `gpt-4o` | Same — retired model |
| `vc-pitch-agent/vc_grader_agent.py` | `whisper-1` | `whisper` | Azure deployment name differs from OpenAI model name |
| `vc-pitch-agent/vc_grader.py` | `whisper-1` | `whisper` | Same as above |

### Azure deployments created
Three model deployments were created in the `exam-grader-openai-3` Azure OpenAI resource (Standard tier):

| Deployment Name | Model | Version | Used By |
|---|---|---|---|
| `gpt-4o` | GPT-4o | 2024-11-20 | Narrative agent, Technical agent |
| `gpt-4o-mini` | GPT-4o Mini | 2024-07-18 | Triage agent, VC pitch agent |
| `whisper` | Whisper | 001 | VC pitch audio transcription |

---

## 2. Bug Fix — Technical Agent Unreachable Code

**File:** `technical-agent/tech_grading_agent.py`

### What was wrong
The entire API call block in `grade_exam()` was unreachable. The function's mock mode check returned early, and due to an indentation mistake, all remaining code (prompt building, API call, response parsing) was nested inside that same `if` block after the `return` statement. In Python, any code after a `return` within the same block is dead code and never executes.

**Before:**
```python
def grade_exam(questions_markdown, answers_text, rubric_markdown=None, model="gpt-4-0125-preview"):
    if is_mock_mode_enabled():
        return _mock_grade_result(questions_markdown)

        # 4-space indent = inside the if block = dead code
        prompt = f"""..."""
        response = openai.chat.completions.create(...)
```

**After:**
```python
def grade_exam(questions_markdown, answers_text, rubric_markdown=None, model="gpt-4o"):
    if is_mock_mode_enabled():
        return _mock_grade_result(questions_markdown)

    # 2-space indent = outside the if block = runs correctly
    prompt = f"""..."""
    response = client.chat.completions.create(...)
```

### Why it mattered
The technical grading agent never called the AI in real mode. It would silently fall through and return `None`, causing the orchestrator to report an error. Real exam grading for technical papers was completely non-functional.

---

## 3. Bug Fix — PDF Table Header Crash

**File:** `multi-agent/agent_orchestrator.py`  
**Function:** `convert_table_to_markdown()` inside `extract_pdf_to_markdown()`

### What was wrong
When extracting tables from student PDF submissions, some table header cells were empty (`None` in Python). The row handling already protected against this with `cell or ""`, but the header line was missing the same protection. Python's `str.join()` raises a `TypeError` if any item in the list is `None` rather than a string.

**Before:**
```python
md = "| " + " | ".join(header) + " |\n"
```

**After:**
```python
md = "| " + " | ".join(cell or "" for cell in header) + " |\n"
```

### Why it mattered
Any student PDF containing a table with empty header cells would crash the text extraction step entirely, returning the error: `sequence item 1: expected str instance, NoneType found`. The file would fail to grade with no useful feedback to the user.

---

## 4. Bug Fix — API Key Check Blocking All Grading

**File:** `multi-agent/batch_grading_ui.py`

### What was wrong
The UI had two places that checked for `OPENAI_API_KEY` before allowing grading to proceed. After the migration to Azure, only `AZURE_OPENAI_API_KEY` is set — so both checks were failing immediately, returning an error before a single API call was even attempted. This caused the "Error" result seen when clicking Grade All immediately after the Azure migration.

**Before (2 occurrences):**
```python
if not os.getenv("OPENAI_API_KEY"):
    return "Error: OPENAI_API_KEY not found..."
```

**After:**
```python
if not os.getenv("AZURE_OPENAI_API_KEY") and not is_mock_mode_enabled():
    return "Error: AZURE_OPENAI_API_KEY not found..."
```

---

## 5. API Timeout Protection

**Files:** All 5 agent files and `agent_orchestrator.py`

### What was added
A `timeout` parameter was added to every API call to prevent the application from hanging indefinitely when Azure does not respond.

| File | Timeout |
|---|---|
| `narrative-agent/exam_grader_agents.py` | 120 seconds |
| `technical-agent/tech_grading_agent.py` | 120 seconds |
| `vc-pitch-agent/vc_grader_agent.py` | 120 seconds |
| `vc-pitch-agent/vc_grader.py` | 120 seconds |
| `multi-agent/agent_orchestrator.py` (triage call) | 60 seconds |

### Why
Without timeouts, a large PDF submission caused the application to hang for 500+ seconds with no response, no error, and no way to know what was happening. With timeouts, the call fails cleanly after the specified duration and returns a human-readable error message to the user.

---

## 6. VC Pitch Score Display Fix

**File:** `multi-agent/batch_grading_ui.py`

### What was wrong
The VC pitch agent returns scores in a unique format with four named dimensions:
```json
{"Problem": 7, "Market": 6, "Solution": 8, "Delivery": 7, "Feedback": "..."}
```

The score extraction logic in the results table only looked for `total_score`, `overall_score`, or a `scores` array — none of which exist in the VC pitch result. It therefore always displayed `N/A` for VC pitch grades even when grading succeeded.

**After:**
```python
elif all(k in grading_result for k in ["Problem", "Market", "Solution", "Delivery"]):
    vc_total = grading_result["Problem"] + grading_result["Market"] + grading_result["Solution"] + grading_result["Delivery"]
    score = f"{vc_total}/40"
```

### Why
The four dimensions are each scored 1–10, giving a maximum of 40. The fix sums them and displays the result as `X/40`, making it immediately meaningful to the user.

---

## 7. Score Display — Added Maximum Mark

**File:** `multi-agent/batch_grading_ui.py`

### What changed
Scores in the results table previously showed a bare number (e.g. `4.5`). They now show the score alongside the maximum (e.g. `4.5/10`, `32.0/40`).

| Agent | Before | After | Max calculation |
|---|---|---|---|
| Narrative | `4.5` | `4.5/10` | Fixed maximum of 10 (average scale) |
| Technical | `32.0` | `32.0/40` | Number of questions × 10 |
| VC Pitch | `N/A` | `28/40` | Sum of 4 dimensions × 10 each |

---

## 8. Error Handling Improvements

**File:** `multi-agent/batch_grading_ui.py`

### What was added
A `friendly_error()` function was introduced that translates raw Python exceptions into plain English messages before displaying them to the user.

```python
def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "Grading timed out — the document may be too large. Try splitting it into smaller sections."
    if "401" in msg or "authentication" in msg.lower():
        return "Azure OpenAI authentication failed — check that your API key and endpoint are correct."
    if "404" in msg or "deployment" in msg.lower():
        return "Model deployment not found — check that the deployment names exist in your Azure resource."
    if "429" in msg or "rate limit" in msg.lower():
        return "Rate limit hit — too many requests. Wait a moment and try again."
    if "NoneType" in msg or "sequence item" in msg.lower():
        return "Could not read the document — the file may be corrupted or password-protected."
    if "audio" in msg.lower() or "whisper" in msg.lower():
        return "Audio transcription failed — make sure the file is a valid MP3/WAV and under 25MB."
    return msg
```

This function is applied to all three exception handlers in `grade_single_student()`.

### Additional UI improvements
- **Error messages no longer truncated** — previously cut off at 50 characters, making them unreadable. Now shown in full.
- **Error rows highlighted in red** — table rows for failed students now have a dark red background (`#3a1a1a`) so failures are immediately visible without reading every cell.

---

## 9. Mock Mode

**Files:** All agent files and orchestrator

### What was added
A `MOCK_MODE` environment variable was wired into all agents. When set to `true`, agents return deterministic fake results without making any API calls. This allows local UI testing and deployment validation without spending Azure credits or requiring a live API connection.

Each agent returns a realistic fake result when mock mode is enabled, including scores, feedback, and a `mock_mode: true` flag in the response.

---

## Environment Variables

The following environment variables must be set in both the local `.env` file and the Azure web app's Application Settings:

| Variable | Description |
|---|---|
| `AZURE_OPENAI_API_KEY` | API key from the `exam-grader-openai-3` Azure OpenAI resource |
| `AZURE_OPENAI_ENDPOINT` | `https://exam-grader-openai-3.openai.azure.com/` |
| `MOCK_MODE` | Optional. Set to `true` to run without API calls for testing |

> **Note:** The `.env` file is listed in `.gitignore` and is never committed to the repository.

---

## Files Changed Summary

| File | Changes |
|---|---|
| `narrative-agent/exam_grader_agents.py` | Azure migration, model update, mock mode, timeout |
| `technical-agent/tech_grading_agent.py` | Azure migration, model update, mock mode, timeout, unreachable code fix |
| `vc-pitch-agent/vc_grader_agent.py` | Azure migration, whisper model name, mock mode, timeout |
| `vc-pitch-agent/vc_grader.py` | Azure migration, whisper model name, mock mode, timeout |
| `multi-agent/agent_orchestrator.py` | Azure migration, PDF table header fix, triage timeout, mock mode |
| `multi-agent/batch_grading_ui.py` | API key check fix, friendly errors, score display, VC pitch score, red error rows |



## Mock Tests without api
cd /Users/sanketsushantpai/Exam-Grading-Agent/multi-agent && \
MOCK_MODE=true python - <<'PY'
from agent_orchestrator import orchestrate_grading

res = orchestrate_grading(
    exam_text='Question 1: Explain normalization in databases.\nQuestion 2: Write SQL to join tables.',
    student_response='Normalization reduces redundancy. SQL join combines rows from related tables.',
    rubric_text='Score each question from 0-10.'
)
print('status:', res.get('orchestration_metadata', {}).get('status'))
print('mock_mode:', res.get('orchestration_metadata', {}).get('mock_mode'))
print('agent_used:', res.get('orchestration_metadata', {}).get('agent_used'))
print('grading_keys:', list(res.get('grading_result', {}).keys())[:5])
PY




cd /Users/sanketsushantpai/Exam-Grading-Agent/multi-agent && \
MOCK_MODE=true python - <<'PY'
from agent_orchestrator import orchestrate_grading, handle_agent_failure

# Technical route
r1 = orchestrate_grading(
    exam_text='Question 1: Write SQL JOIN query.\nQuestion 2: Explain algorithm complexity.',
    student_response='Use INNER JOIN on key. Complexity can be O(n log n).',
    rubric_text='Score from 0-10', enable_triage=True
)

# Narrative route
r2 = orchestrate_grading(
    exam_text='Question 1: Discuss leadership in uncertain markets.\nQuestion 2: Reflect on strategy tradeoffs.',
    student_response='Leaders align teams and communicate clearly under ambiguity.',
    rubric_text='Assess depth, reflection, and argument quality.', enable_triage=True
)

# VC pitch route
r3 = orchestrate_grading(
    exam_text='', student_response='', rubric_text='',
    exam_type_override='vc_pitch', enable_triage=False, audio_file='dummy_pitch.mp3'
)

# Handoff/fallback route
r4 = handle_agent_failure(
    failed_exam_type='technical',
    exam_text='Question 1: Reflect on customer adoption strategy.',
    student_response='Adoption improves with strong onboarding and retention loops.',
    rubric_text='Score clarity and evidence.', error='Simulated upstream error'
)

for name, res in [('technical', r1), ('narrative', r2), ('vc_pitch', r3)]:
    meta = res.get('orchestration_metadata', {})
    print(f"{name}: status={meta.get('status')} agent={meta.get('agent_used')} error={'error' in res.get('grading_result', {})}")

print(f"handoff: error={r4.get('error')} fallback={r4.get('handoff_metadata', {}).get('fallback_agent')}")
PY




cd /Users/sanketsushantpai/Exam-Grading-Agent/multi-agent && \
MOCK_MODE=true python batch_grading_ui.py