import httpx
from voice_blueprint_shared.job import Job

from scheduler.config import settings


async def initiate_outbound(job: Job) -> dict:
    """Call agent-connect to initiate an outbound conversation for this Job."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.agent_connect_url}/outbound",
            json=job.model_dump(by_alias=True, mode="json"),
        )
        resp.raise_for_status()
        return resp.json()
