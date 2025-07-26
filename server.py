#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""RTVI Bot Server Implementation.

This FastAPI server manages RTVI bot instances and provides endpoints for both
direct browser access and RTVI client connections. It handles:
- Creating Daily rooms
- Managing bot processes
- Providing connection credentials
- Monitoring bot status
- JWT authentication with configurable identity servers

Requirements:
- Daily API key (set in .env file)
- Python 3.12+
- FastAPI
- Running bot implementation
- JWT identity server (optional, configurable via environment variables)
"""

import argparse
import os
import shlex
import subprocess
import json
from contextlib import asynccontextmanager
from typing import Any, Dict

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper, DailyRoomParams
from auth import verify_auth

# Load environment variables from .env file
load_dotenv(override=True)

# Maximum number of bot instances allowed per room
MAX_BOTS_PER_ROOM = 1

# Dictionary to track bot processes: {pid: (process, room_url)}
bot_procs = {}

# Store Daily API helpers
daily_helpers = {}


def get_bot_file(bot_type: str = None):
    """Get the bot implementation file based on bot_type or environment variable.

    Args:
        bot_type (str, optional): Bot implementation type. If None, uses BOT_IMPLEMENTATION env var.

    Returns:
        str: The bot file module name (e.g., "bot-nova")

    Raises:
        ValueError: If the bot_type is not valid
    """
    if bot_type:
        bot_implementation = bot_type.lower().strip()
    else:
        bot_implementation = os.getenv("BOT_IMPLEMENTATION", "nova").lower().strip()

    # If blank or None, default to nova
    if not bot_implementation:
        bot_implementation = "nova"

    if bot_implementation not in ["openai", "gemini", "nova", "polly"]:
        raise ValueError(
            f"Invalid bot implementation: {bot_implementation}. Must be 'openai', 'gemini', 'nova', or 'polly'"
        )
    return f"bot-{bot_implementation}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager that handles startup and shutdown tasks.

    - Creates aiohttp session
    - Initializes Daily API helper
    - Cleans up resources on shutdown
    """
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=os.getenv("DAILY_API_KEY", ""),
        daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
        aiohttp_session=aiohttp_session,
    )
    yield
    await aiohttp_session.close()


# Initialize FastAPI app with lifespan manager
app = FastAPI(lifespan=lifespan)

# Configure CORS to allow requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def create_room_and_token() -> tuple[str, str]:
    """Helper function to create a Daily room and generate an access token.

    Returns:
        tuple[str, str]: A tuple containing (room_url, token)

    Raises:
        HTTPException: If room creation or token generation fails
    """
    room_url = os.getenv("DAILY_SAMPLE_ROOM_URL", None)
    token = os.getenv("DAILY_SAMPLE_ROOM_TOKEN", None)
    if not room_url:
        room = await daily_helpers["rest"].create_room(DailyRoomParams())
        if not room.url:
            raise HTTPException(status_code=500, detail="Failed to create room")
        room_url = room.url

        token = await daily_helpers["rest"].get_token(room_url)
        if not token:
            raise HTTPException(status_code=500, detail=f"Failed to get token for room: {room_url}")

    return room_url, token


@app.get("/")
async def start_agent(request: Request, bot: str = None, username: str = Depends(verify_auth)):
    """Endpoint for direct browser access to the bot.

    Creates a room, starts a bot instance, and redirects to the Daily room URL.
    Requires basic authentication.

    Args:
        bot (str, optional): Bot implementation type (openai, gemini, nova, polly). 
                           If not provided, uses BOT_IMPLEMENTATION env var.
        username (str): Authenticated username (injected by dependency)

    Returns:
        RedirectResponse: Redirects to the Daily room URL

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    bot_type = bot if bot else None
    print(f"Creating room with bot type: {bot_type or 'default'} for user: {username}")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Check if there is already an existing process running in this room
    num_bots_in_room = sum(
        1 for proc in bot_procs.values() if proc[1] == room_url and proc[0].poll() is None
    )
    if num_bots_in_room >= MAX_BOTS_PER_ROOM:
        raise HTTPException(status_code=500, detail=f"Max bot limit reached for room: {room_url}")

    # Spawn a new bot process
    try:
        bot_file = get_bot_file(bot_type)
        proc = subprocess.Popen(
            [f"python3 -m {bot_file} -u {room_url} -t {token}"],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return RedirectResponse(room_url)


@app.get("/up")
async def health_check():
    return {"status": "ok"}

@app.post("/connect")
async def rtvi_connect(request: Request, bot: str = None, username: str = Depends(verify_auth)) -> Dict[Any, Any]:
    """RTVI connect endpoint that creates a room and returns connection credentials.

    This endpoint is called by RTVI clients to establish a connection.
    Requires authentication (JWT Bearer token or Basic Auth).
    Optionally accepts system_prompt and tools in the JSON body, which are passed to the bot process as a single JSON argument.

    Args:
        bot (str, optional): Bot implementation type (openai, gemini, nova, polly). 
                           If not provided, uses BOT_IMPLEMENTATION env var.
        username (str): Authenticated username (injected by dependency)

    Returns:
        Dict[Any, Any]: Authentication bundle containing room_url and token

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    bot_type = bot if bot else None
    print(f"Creating room for RTVI connection with bot type: {bot_type or 'default'}")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Parse system_prompt and tools from JSON body
    try:
        body = await request.json()
    except Exception:
        body = {}
    system_prompt = body.get("system_prompt")
    tools = body.get("tools")
    learning_context = body.get("learning_context")
    custom_payload = None
    if system_prompt is not None or tools is not None or learning_context is not None:
        custom_payload = json.dumps({
            "system_prompt": system_prompt, 
            "tools": tools,
            "learning_context": learning_context
        })

    # Start the bot process
    try:
        bot_file = get_bot_file(bot_type)
        cmd = [f"python3 -m {bot_file} -u {room_url} -t {token}"]
        if custom_payload:
            cmd[0] += f" -c {shlex.quote(custom_payload)}"
        proc = subprocess.Popen(
            cmd,
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    # Return the authentication bundle in format expected by DailyTransport
    return {"room_url": room_url, "token": token}


@app.post("/connect/{bot_type}")
async def rtvi_connect_with_bot_type(request: Request, bot_type: str, username: str = Depends(verify_auth)) -> Dict[Any, Any]:
    """RTVI connect endpoint with specified bot type that creates a room and returns connection credentials.

    This endpoint is called by RTVI clients to establish a connection with a specific bot type.
    Requires authentication (JWT Bearer token or Basic Auth).
    Optionally accepts system_prompt and tools in the JSON body, which are passed to the bot process as a single JSON argument.

    Args:
        bot_type (str): Bot implementation type (openai, gemini, nova, polly)
        username (str): Authenticated username (injected by dependency)

    Returns:
        Dict[Any, Any]: Authentication bundle containing room_url and token

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    # Validate bot_type before proceeding
    if bot_type.lower() not in ["openai", "gemini", "nova", "polly"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid bot type: {bot_type}. Must be 'openai', 'gemini', 'nova', or 'polly'"
        )
    print(f"Creating room for RTVI connection with bot type: {bot_type}")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Parse system_prompt and tools from JSON body
    try:
        body = await request.json()
    except Exception:
        body = {}
    system_prompt = body.get("system_prompt")
    tools = body.get("tools")
    learning_context = body.get("learning_context")
    custom_payload = None
    if system_prompt is not None or tools is not None or learning_context is not None:
        custom_payload = json.dumps({
            "system_prompt": system_prompt, 
            "tools": tools,
            "learning_context": learning_context
        })

    # Start the bot process
    try:
        bot_file = get_bot_file(bot_type)
        cmd = [f"python3 -m {bot_file} -u {room_url} -t {token}"]
        if custom_payload:
            cmd[0] += f" -c {shlex.quote(custom_payload)}"
        proc = subprocess.Popen(
            cmd,
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    # Return the authentication bundle in format expected by DailyTransport
    return {"room_url": room_url, "token": token}


@app.get("/status/{pid}")
def get_status(pid: int):
    """Get the status of a specific bot process.

    Args:
        pid (int): Process ID of the bot

    Returns:
        JSONResponse: Status information for the bot

    Raises:
        HTTPException: If the specified bot process is not found
    """
    # Look up the subprocess
    proc = bot_procs.get(pid)

    # If the subprocess doesn't exist, return an error
    if not proc:
        raise HTTPException(status_code=404, detail=f"Bot with process id: {pid} not found")

    # Check the status of the subprocess
    status = "running" if proc[0].poll() is None else "finished"
    return JSONResponse({"bot_id": pid, "status": status})


@app.get("/{bot_type}")
async def start_agent_with_bot_type(request: Request, bot_type: str, username: str = Depends(verify_auth)):
    """Endpoint for direct browser access to the bot with specified bot type.

    Creates a room, starts a bot instance of the specified type, and redirects to the Daily room URL.
    Requires basic authentication.

    Args:
        bot_type (str): Bot implementation type (openai, gemini, nova, polly)
        username (str): Authenticated username (injected by dependency)

    Returns:
        RedirectResponse: Redirects to the Daily room URL

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    # Validate bot_type before proceeding
    if bot_type.lower() not in ["openai", "gemini", "nova", "polly"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid bot type: {bot_type}. Must be 'openai', 'gemini', 'nova', or 'polly'"
        )

    print(f"Creating room with bot type: {bot_type} for user: {username}")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Check if there is already an existing process running in this room
    num_bots_in_room = sum(
        1 for proc in bot_procs.values() if proc[1] == room_url and proc[0].poll() is None
    )
    if num_bots_in_room >= MAX_BOTS_PER_ROOM:
        raise HTTPException(status_code=500, detail=f"Max bot limit reached for room: {room_url}")

    # Spawn a new bot process
    try:
        bot_file = get_bot_file(bot_type)
        proc = subprocess.Popen(
            [f"python3 -m {bot_file} -u {room_url} -t {token}"],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return RedirectResponse(room_url)


if __name__ == "__main__":
    import uvicorn

    # Parse command line arguments for server configuration
    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("FAST_API_PORT", "8080"))

    parser = argparse.ArgumentParser(description="Daily Storyteller FastAPI server")
    parser.add_argument("--host", type=str, default=default_host, help="Host address")
    parser.add_argument("--port", type=int, default=default_port, help="Port number")
    parser.add_argument("--reload", action="store_true", help="Reload code on change")

    config = parser.parse_args()

    # Start the FastAPI server
    uvicorn.run(
        "server:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
    )
