import os

from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health():
    # version = the git sha baked into the image at build time (deploy.yml
    # passes GIT_SHA). Empty on local/dev builds. This is how we tell WHICH
    # commit the box is actually running — the box pulls :latest on a timer,
    # so "did the deploy land?" was unanswerable before this field.
    return {"status": "ok", "version": os.environ.get("GIT_SHA", "")}
