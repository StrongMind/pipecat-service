import asyncio
import os
import argparse
import aiohttp
from dotenv import load_dotenv

from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.aws.stt import AWSTranscribeSTTService
from pipecat.services.aws.tts import AWSPollyTTSService
from pipecat.services.aws.llm import AWSBedrockLLMService, AWSBedrockLLMContext
from pipecat.transports.services.daily import DailyParams, DailyTransport

load_dotenv(override=True)


async def main(room_url, token):
    """Main bot execution function.

    Sets up and runs the bot pipeline including:
    - Set up WebRTC transport
    - Speech-to-text and text-to-speech services
    - Language model integration
    """
    async with aiohttp.ClientSession() as session:
        print(f"Starting server with room: {room_url}")

        # Set up Daily transport with audio parameters
        transport = DailyTransport(
            room_url,
            token,
            "Amazon Voice AI Agent",
            DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                camera_in_enabled=False,
                camera_out_enabled=False,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(stop_secs=0.5)
                ),
                transcription_enabled=True,
            ),
        )

        # Initialize speech-to-text service
        stt = AWSTranscribeSTTService(
            api_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
            region=os.getenv("AWS_REGION")
        )

        # Initialize text-to-speech service
        tts = AWSPollyTTSService(
            api_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
            region=os.getenv("AWS_REGION"),
            voice_id="Joanna",
            params=AWSPollyTTSService.InputParams(
                engine="generative",
                language="en-US",
                rate="1.1"
            )
        )

        # Initialize LLM service
        llm = AWSBedrockLLMService(
            aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
            aws_region=os.getenv("AWS_REGION"),
            model="us.anthropic.claude-3-5-haiku-20241022-v1:0",
            params=AWSBedrockLLMService.InputParams(

                temperature=0.3,
                latency="optimized",
                additional_model_request_fields={}
            )
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a elementary school teacher named Lexi in a WebRTC "
                    "call. Your goal is to demonstrate your capabilities in a "
                    "succinct way. Your output will be converted to audio so "
                    "don't include special characters in your answers. Respond "
                    "to what the user said in a creative and helpful way."
                ),
            },
        ]

        context = OpenAILLMContext(messages)
        context_aggregator = llm.create_context_aggregator(context)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
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
            ),
        )

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            await transport.capture_participant_transcription(
                participant["id"]
            )
            # await task.queue_frames(
            #     [context_aggregator.user().get_context_frame()]
            # )

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            print(f"Participant left: {participant}")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)
        await runner.run(task)


if __name__ == "__main__":
    # Parse command line arguments for server configuration
    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("FAST_API_PORT", "7860"))

    parser = argparse.ArgumentParser(description="Daily FastAPI server")
    parser.add_argument("-u", "--url", type=str, help="Daily room url")
    parser.add_argument("-t", "--token", type=str, help="Daily room token")

    config = parser.parse_args()

    asyncio.run(main(config.url, config.token))
