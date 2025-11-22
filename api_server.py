from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
import uvicorn

# Import your existing logic
from db.db import get_session
from db.models import Job, ApplicationPackage
from agents.ingestion import ingest_all
from agents.analysis import analyze_job, filter_jobs, rank_jobs
from agents.resume_writer import build_granite_resume, build_cheat_sheet
from agents.ghost_validator import validate_job
from db.persist import upsert_jobs, save_application

app = FastAPI(title="ResumeGenie API")

# Allow Next.js (port 3000) to talk to Python (port 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def run_ingestion_pipeline(db: Session):
    """Background task to fetch and process jobs"""
    print("Starting ingestion...")
    jobs = ingest_all()
    jobs = [analyze_job(j) for j in jobs]
    # Simple default filter
    jobs = filter_jobs(jobs, {"skills": ["Python", "AWS"], "remote_only": True})
    jobs = rank_jobs(jobs)
    upsert_jobs(db, jobs)
    print(f"Ingestion complete. Processed {len(jobs)} jobs.")

@app.get("/jobs")
def get_jobs(limit: int = 20, db: Session = Depends(get_session)):
    return db.query(Job).order_by(Job.score.desc()).limit(limit).all()

@app.post("/ingest")
def trigger_ingest(background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    """Trigger the ingestion pipeline in the background"""
    background_tasks.add_task(run_ingestion_pipeline, db)
    return {"status": "Ingestion started in background"}

@app.post("/generate/{job_id}")
def generate_application(job_id: str, db: Session = Depends(get_session)):
    """Generate resume and cheat sheet for a specific job"""
    job_record = db.query(Job).filter(Job.id == job_id).first()
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Convert SQLAlchemy model to dict for your existing agents
    job_dict = {c.name: getattr(job_record, c.name) for c in job_record.__table__.columns}
    
    # Mock profile for now (In real app, fetch from DB/Request)
    profile = {
        "skills": ["Python", "AWS", "Terraform"], 
        "experience": [{"action": "Built API", "context": "FastAPI", "result": "Fast"}]
    }
    
    # Run generation logic
    resume = build_granite_resume(profile, job_dict, []) # Empty projects for now
    cheat = build_cheat_sheet(profile, job_dict)
    
    # Save to DB
    pkg_id = save_application(db, job_id, resume, cheat, "user@example.com", 0)
    return {"status": "Generated", "package_id": pkg_id, "resume": resume}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
