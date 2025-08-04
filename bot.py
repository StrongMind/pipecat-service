#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.aws_nova_sonic import AWSNovaSonicLLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecatcloud.agent import DailySessionArguments

# Load environment variables
load_dotenv(override=True)

# Check if we're in local development mode
LOCAL_RUN = os.getenv("LOCAL_RUN")
if LOCAL_RUN:
    import asyncio
    import webbrowser

    try:
        from local_runner import configure
    except ImportError:
        logger.error(
            "Could not import local_runner module. "
            "Local development mode may not work."
        )


async def main(transport: DailyTransport):
    """Main pipeline setup and execution function.

    Args:
        transport: The DailyTransport instance
    """

    llm = AWSNovaSonicLLMService(
        secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        region="us-east-1",
        voice_id="tiffany",  # matthew, tiffany, amy
        # you could choose to pass instruction here rather than via context
        # system_instruction=system_instruction
        # you could choose to pass tools here rather than via context
        # tools=tools
    )

    system_instruction = (
        "You are a elementary school teacher named Lexi. "
        f"{AWSNovaSonicLLMService.AWAIT_TRIGGER_ASSISTANT_RESPONSE_INSTRUCTION}"
    )
    messages = [
        {
            "role": "system",
            "content": system_instruction,
        },
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=True,
        ),
    )

    # Handle client connection event
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.info("First participant joined: {}", participant["id"])
        await transport.capture_participant_transcription(participant["id"])
        # Kick off the conversation.
        await task.queue_frames([context_aggregator.user().get_context_frame()])
        # HACK: for now, we need this special way of triggering the first
        # assistant response in AWS Nova Sonic. Note that this trigger
        # requires a special corresponding bit of text in the system
        # instruction. In the future, simply queueing the context frame
        # should be sufficient.
        await llm.trigger_assistant_response()

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info("Participant left: {}", participant)
        await task.cancel()

    runner = PipelineRunner()

    await runner.run(task)


async def bot(args: DailySessionArguments):
    """Main bot entry point compatible with the FastAPI route handler.

    Args:
        room_url: The Daily room URL
        token: The Daily room token
        body: The configuration object from the request body
        session_id: The session ID for logging
    """
    logger.info(f"Bot process initialized {args.room_url} {args.token}")

    transport = DailyTransport(
        args.room_url,
        args.token,
        "Pipecat Bot",
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            transcription_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    try:
        await main(transport)
        logger.info("Bot process completed")
    except Exception as e:
        logger.exception(f"Error in bot process: {str(e)}")
        raise


# Local development
async def local_daily():
    """Daily transport for local development."""

    try:
        async with aiohttp.ClientSession() as session:
            (room_url, token) = await configure(session)
            transport = DailyTransport(
                room_url,
                token,
                "Pipecat Local Bot",
                params=DailyParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    transcription_enabled=True,
                    vad_analyzer=SileroVADAnalyzer(),
                ),
            )

            logger.warning(f"Talk to your voice agent here: {room_url}")
            webbrowser.open(room_url)

            await main(transport)
    except Exception as e:
        logger.exception(f"Error in local development mode: {e}")


# Local development entry point
if LOCAL_RUN and __name__ == "__main__":
    try:
        asyncio.run(local_daily())
    except Exception as e:
        logger.exception(f"Failed to run in local mode: {e}")
