from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.agent import IncidentAgent
from app.config import get_settings
from app.data import FixtureDataStore, PostgresDataStore
from app.models import InvestigateRequest, InvestigationResult

app = FastAPI(
    title="OpsPilot",
    version="1.0.0",
    description="Evidence-grounded, approval-gated incident response",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/investigate", response_model=InvestigationResult)
def investigate(request: InvestigateRequest) -> InvestigationResult:
    try:
        datastore = (
            FixtureDataStore(request.seed)
            if request.seed
            else PostgresDataStore(get_settings().database_url)
        )
        return IncidentAgent(datastore, prompt_variant=request.prompt_variant).investigate(
            request.description
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
