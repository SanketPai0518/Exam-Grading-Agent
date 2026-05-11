"""
FastAPI wrapper for the Exam Grading Agent
Exposes the orchestrator as a REST API on port 8002
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure the multi-agent directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_orchestrator import orchestrate_grading, extract_pdf_to_markdown

app = FastAPI(title="Exam Grading Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/grade")
async def grade(
    exam_file: UploadFile = File(...),
    student_file: UploadFile = File(...),
    rubric_file: Optional[UploadFile] = File(None),
    student_name: Optional[str] = Form(None),
):
    """
    Grade a student exam submission.

    - exam_file: PDF/TXT file containing the exam questions
    - student_file: PDF/TXT/image/audio file with the student response
    - rubric_file: optional rubric PDF/TXT
    - student_name: optional display name for the student
    """
    tmp_paths = []
    try:
        # Save uploaded files to temp paths so the orchestrator can read them
        def save_upload(upload: UploadFile) -> str:
            suffix = Path(upload.filename).suffix if upload.filename else ".tmp"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(upload.file.read())
            tmp.flush()
            tmp_paths.append(tmp.name)
            return tmp.name

        exam_path    = save_upload(exam_file)
        student_path = save_upload(student_file)
        rubric_path  = save_upload(rubric_file) if rubric_file else None

        audio_extensions = {".mp3", ".wav", ".mp4", ".m4a", ".ogg"}
        text_extensions  = {".txt", ".md"}

        def extract_text(path: str) -> str:
            suffix = Path(path).suffix.lower()
            if suffix in audio_extensions:
                return ""          # audio — no text extraction
            if suffix in text_extensions:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            return extract_pdf_to_markdown(path)   # PDF or image

        is_audio = Path(student_path).suffix.lower() in audio_extensions

        exam_text    = extract_text(exam_path)
        student_text = "" if is_audio else extract_text(student_path)
        rubric_text  = extract_text(rubric_path) if rubric_path else ""

        result = orchestrate_grading(
            exam_text=exam_text,
            student_response=student_text,
            rubric_text=rubric_text,
            audio_file=student_path if is_audio else None,
        )

        return {
            "student_name": student_name or Path(student_file.filename or "student").stem,
            "grading_result": result.get("grading_result", {}),
            "metadata": result.get("orchestration_metadata", {}),
            "error": result.get("error"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    uvicorn.run("api:app", host="127.0.0.1", port=8002, reload=True)
