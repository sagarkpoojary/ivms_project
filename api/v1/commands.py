from fastapi import APIRouter, Depends, HTTPException
import asyncpg
import os
from pydantic import BaseModel
from typing import Optional
from core.commands import CommandEngine
from core.cache import LiveCache

router = APIRouter(prefix="/api/v2/commands", tags=["Commands"])
cache = LiveCache()

DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

class CommandRequest(BaseModel):
    imei: str
    type: str # reboot, setparam, getgps
    payload: Optional[str] = None

async def get_engine():
    pool = await asyncpg.create_pool(dsn=DB_URL)
    await cache.connect()
    engine = CommandEngine(pool, cache)
    try:
        yield engine
    finally:
        await pool.close()

@router.post("/send")
async def send_command(req: CommandRequest, engine: CommandEngine = Depends(get_engine)):
    try:
        cmd_id = await engine.queue_command(req.imei, req.type, req.payload)
        return {"status": "queued", "command_id": cmd_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/status/{command_id}")
async def get_command_status(command_id: int):
    # This would normally query the DB for the status
    # For now, we assume a database pool is available in the context
    pass
