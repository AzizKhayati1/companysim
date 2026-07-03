"""Run a simulation against the current persisted org state.

Reads the DB (via `converters.org_to_pydantic`) but never writes back — a
simulation run is a stochastic "what if," not a mutation. Edits only ever
happen through the CRUD routers, keeping "edit, run, look, edit again" a
clean loop.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from companysim.api.converters import org_to_pydantic
from companysim.api.database import get_db
from companysim.api.scenario_builder import build_scenario
from companysim.api.schemas import SimulateRequest, SimulateResponse
from companysim.mc.runner import MonteCarloRunner
from companysim.model.organization import OrganizationModel

router = APIRouter(prefix="/orgs/{org_id}", tags=["simulate"])


@router.post("/simulate", response_model=SimulateResponse)
def simulate(org_id: int, req: SimulateRequest, db: Session = Depends(get_db)):
    try:
        org, hf_df = org_to_pydantic(db, org_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    scenario = build_scenario(req.events)

    if req.replicates <= 1:
        model = OrganizationModel(
            organization=org, seed=req.seed, scenario=scenario, human_factors=hf_df,
        )
        hist = model.run(req.ticks)
        return SimulateResponse(
            mode="single", ticks=req.ticks, replicates=1,
            columns=list(hist.columns), rows=hist.to_dict(orient="records"),
        )

    runner = MonteCarloRunner(
        scenario=scenario, base_org=org, human_factors=hf_df,
        replicates=req.replicates, ticks=req.ticks, base_seed=req.seed,
    )
    result = runner.run()
    return SimulateResponse(
        mode="monte_carlo", ticks=req.ticks, replicates=req.replicates,
        columns=list(result.bands.columns), rows=result.bands.to_dict(orient="records"),
    )
