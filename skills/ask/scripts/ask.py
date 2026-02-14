#!/usr/bin/env python3
"""
Multi-model query system for Claude Code.
Supports GSwarm (Gemini), OpenAI (GPT/O3), and Ollama (local models).
"""

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import aiohttp
    from aiohttp import ClientTimeout
except ImportError:
    print("Error: aiohttp not installed. Run: uv pip install aiohttp", file=sys.stderr)
    sys.exit(1)


@dataclass
class ModelResponse:
    """Response from a single model."""
    model: str
    response: str
    elapsed_ms: int
    error: Optional[str] = None


@dataclass
class ProviderConfig:
    """Configuration for a provider endpoint."""
    name: str
    base_url: str
    api_key: Optional[str] = None

    def get_url(self, path: str) -> str:
        """Construct full URL for endpoint."""
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


class MultiModelClient:
    """Client for querying multiple AI models in parallel."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.providers = self._load_providers()

    def _load_providers(self) -> Dict[str, ProviderConfig]:
        """Load provider configs from environment."""
        return {
            'gswarm': ProviderConfig(
                name='gswarm',
                base_url=os.getenv('GSWARM_BASE_URL', 'http://localhost:4000'),
            ),
            'openai': ProviderConfig(
                name='openai',
                base_url='https://api.openai.com',
                api_key=os.getenv('OPENAI_API_KEY'),
            ),
            'ollama': ProviderConfig(
                name='ollama',
                base_url=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
            ),
        }

    def detect_provider(self, model: str) -> str:
        """Detect provider from model name."""
        if re.match(r'^gemini', model, re.IGNORECASE):
            return 'gswarm'
        elif re.match(r'^(gpt|o3)', model, re.IGNORECASE):
            return 'openai'
        elif re.match(r'^(llama|codellama|deepseek|qwen|mistral)', model, re.IGNORECASE):
            return 'ollama'
        else:
            # Default to gswarm for unknown models
            return 'gswarm'

    async def query_gswarm(
        self,
        session: aiohttp.ClientSession,
        model: str,
        question: str,
    ) -> Tuple[str, int]:
        """Query GSwarm (Gemini) via OpenAI-compatible endpoint."""
        provider = self.providers['gswarm']
        url = provider.get_url('/v1/chat/completions')

        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': question}],
            'temperature': 0.7,
        }

        start = time.time()
        timeout = ClientTimeout(total=self.timeout)

        async with session.post(url, json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json()
            elapsed_ms = int((time.time() - start) * 1000)

            # Extract response from OpenAI-compatible format
            content = data['choices'][0]['message']['content']
            return content, elapsed_ms

    async def query_openai(
        self,
        session: aiohttp.ClientSession,
        model: str,
        question: str,
    ) -> Tuple[str, int]:
        """Query OpenAI API (GPT/O3)."""
        provider = self.providers['openai']

        if not provider.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        url = provider.get_url('/v1/chat/completions')

        headers = {
            'Authorization': f'Bearer {provider.api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': question}],
            'temperature': 0.7,
        }

        start = time.time()
        timeout = ClientTimeout(total=self.timeout)

        async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json()
            elapsed_ms = int((time.time() - start) * 1000)

            content = data['choices'][0]['message']['content']
            return content, elapsed_ms

    async def query_ollama(
        self,
        session: aiohttp.ClientSession,
        model: str,
        question: str,
    ) -> Tuple[str, int]:
        """Query Ollama local endpoint."""
        provider = self.providers['ollama']
        url = provider.get_url('/api/generate')

        payload = {
            'model': model,
            'prompt': question,
            'stream': False,
        }

        start = time.time()
        timeout = ClientTimeout(total=self.timeout)

        async with session.post(url, json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json()
            elapsed_ms = int((time.time() - start) * 1000)

            content = data['response']
            return content, elapsed_ms

    async def query_model(
        self,
        session: aiohttp.ClientSession,
        model: str,
        question: str,
    ) -> ModelResponse:
        """Query a single model with error handling."""
        provider_name = self.detect_provider(model)

        try:
            if provider_name == 'gswarm':
                content, elapsed_ms = await self.query_gswarm(session, model, question)
            elif provider_name == 'openai':
                content, elapsed_ms = await self.query_openai(session, model, question)
            elif provider_name == 'ollama':
                content, elapsed_ms = await self.query_ollama(session, model, question)
            else:
                raise ValueError(f"Unknown provider: {provider_name}")

            return ModelResponse(
                model=model,
                response=content,
                elapsed_ms=elapsed_ms,
            )

        except asyncio.TimeoutError:
            return ModelResponse(
                model=model,
                response='',
                elapsed_ms=self.timeout * 1000,
                error=f'Timeout after {self.timeout}s',
            )
        except Exception as e:
            return ModelResponse(
                model=model,
                response='',
                elapsed_ms=0,
                error=str(e),
            )

    async def query_all(
        self,
        models: List[str],
        question: str,
    ) -> List[ModelResponse]:
        """Query multiple models in parallel."""
        async with aiohttp.ClientSession() as session:
            tasks = [
                self.query_model(session, model, question)
                for model in models
            ]
            return await asyncio.gather(*tasks)


def format_table(responses: List[ModelResponse], show_full: bool = False) -> str:
    """Format responses as ASCII table."""
    lines = []

    # Header
    lines.append("┌" + "─" * 20 + "┬" + "─" * 80 + "┬" + "─" * 15 + "┐")
    lines.append("│ Model              │ Response" + " " * 72 + "│ Time (ms)     │")
    lines.append("├" + "─" * 20 + "┼" + "─" * 80 + "┼" + "─" * 15 + "┤")

    for resp in responses:
        if resp.error:
            # Error row
            model_cell = f" {resp.model:<18} "
            error_cell = f" ❌ {resp.error:<76} "
            time_cell = f" —             "
            lines.append(f"│{model_cell}│{error_cell}│{time_cell}│")
        else:
            # Success row
            model_cell = f" {resp.model:<18} "

            # Truncate response if not showing full
            response_text = resp.response
            if not show_full:
                response_text = response_text[:200] + "..." if len(response_text) > 200 else response_text

            # Wrap response to fit column width
            response_lines = []
            for i in range(0, len(response_text), 78):
                chunk = response_text[i:i+78]
                response_lines.append(f" {chunk:<78} ")

            time_cell = f" {resp.elapsed_ms:<13} "

            # First line with model and time
            lines.append(f"│{model_cell}│{response_lines[0] if response_lines else ' ' * 80}│{time_cell}│")

            # Additional lines for wrapped text
            for line in response_lines[1:]:
                lines.append(f"│{' ' * 20}│{line}│{' ' * 15}│")

    # Footer
    lines.append("└" + "─" * 20 + "┴" + "─" * 80 + "┴" + "─" * 15 + "┘")

    return "\n".join(lines)


def format_consensus(responses: List[ModelResponse]) -> str:
    """Format consensus mode output with agreement analysis."""
    lines = []

    # Show table
    lines.append(format_table(responses, show_full=False))
    lines.append("")

    # Analyze consensus
    successful = [r for r in responses if not r.error]

    if len(successful) == 0:
        lines.append("**Consensus:** No models responded successfully")
    elif len(successful) == 1:
        lines.append("**Consensus:** Only one model responded")
    else:
        # Simple consensus check: look for common keywords
        all_text = " ".join([r.response.lower() for r in successful])

        # Look for agreement indicators
        positive_words = ['yes', 'should', 'recommend', 'good', 'better']
        negative_words = ['no', 'avoid', 'don\'t', 'shouldn\'t', 'worse']

        positive_count = sum(1 for word in positive_words if word in all_text)
        negative_count = sum(1 for word in negative_words if word in all_text)

        if positive_count > negative_count * 2:
            consensus = f"Majority positive ({len(successful)} models)"
        elif negative_count > positive_count * 2:
            consensus = f"Majority negative ({len(successful)} models)"
        else:
            consensus = f"Mixed opinions ({len(successful)} models)"

        lines.append(f"**Consensus:** {consensus}")

    return "\n".join(lines)


def format_markdown(responses: List[ModelResponse]) -> str:
    """Format responses as markdown."""
    lines = []

    lines.append("| Model | Response | Time (ms) |")
    lines.append("|-------|----------|-----------|")

    for resp in responses:
        if resp.error:
            lines.append(f"| {resp.model} | ❌ {resp.error} | — |")
        else:
            # Truncate response for table
            response_text = resp.response[:200] + "..." if len(resp.response) > 200 else resp.response
            # Escape pipes in response
            response_text = response_text.replace('|', '\\|')
            lines.append(f"| {resp.model} | {response_text} | {resp.elapsed_ms} |")

    return "\n".join(lines)


def format_json(responses: List[ModelResponse]) -> str:
    """Format responses as JSON."""
    data = [
        {
            'model': r.model,
            'response': r.response,
            'elapsed_ms': r.elapsed_ms,
            'error': r.error,
        }
        for r in responses
    ]
    return json.dumps(data, indent=2)


def show_help():
    """Show usage help."""
    print("""
/ask - Multi-Model Query System

Usage:
  /ask "question" [options]

Options:
  --models MODEL[,MODEL...]   Comma-separated model list (default: gemini-2.0-flash)
  --mode MODE                 Query mode: chat, consensus, codereview (default: chat)
  --timeout SECONDS           Timeout per model (default: 30)
  --format FORMAT             Output format: table, markdown, json (default: table)

Modes:
  chat        Single model query (uses first model in list)
  consensus   All models answer independently, compare results
  codereview  Send code context to all models, aggregate findings

Examples:
  /ask "Explain async/await in Python"
  /ask "Should I use REST or GraphQL?" --mode consensus --models gemini-2.0-flash,gpt-4o
  /ask "Review this auth flow" --mode codereview --models gemini-2.0-flash,gpt-4o
  /ask "Complex query" --timeout 60 --format json

Supported Models:
  GSwarm:  gemini-2.0-flash, gemini-2.0-flash-thinking, gemini-1.5-pro
  OpenAI:  gpt-4o, gpt-4o-mini, o3-mini
  Ollama:  llama3.2, codellama, deepseek-coder

Environment Variables:
  OPENAI_API_KEY      OpenAI API key (required for GPT/O3 models)
  GSWARM_BASE_URL     GSwarm endpoint (default: http://localhost:4000)
  OLLAMA_BASE_URL     Ollama endpoint (default: http://localhost:11434)
""")


def parse_args(args: List[str]) -> Dict[str, Any]:
    """Parse command-line arguments."""
    if not args or args[0] in ['help', '--help', '-h']:
        show_help()
        sys.exit(0)

    # Extract question (first positional arg)
    question = args[0]

    # Defaults
    config = {
        'question': question,
        'models': ['gemini-2.0-flash'],
        'mode': 'chat',
        'timeout': 30,
        'format': 'table',
    }

    # Parse flags
    i = 1
    while i < len(args):
        arg = args[i]

        if arg == '--models':
            if i + 1 >= len(args):
                print("Error: --models requires a value", file=sys.stderr)
                sys.exit(1)
            config['models'] = args[i + 1].split(',')
            i += 2
        elif arg == '--mode':
            if i + 1 >= len(args):
                print("Error: --mode requires a value", file=sys.stderr)
                sys.exit(1)
            mode = args[i + 1]
            if mode not in ['chat', 'consensus', 'codereview']:
                print(f"Error: Invalid mode '{mode}'. Use: chat, consensus, codereview", file=sys.stderr)
                sys.exit(1)
            config['mode'] = mode
            i += 2
        elif arg == '--timeout':
            if i + 1 >= len(args):
                print("Error: --timeout requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                config['timeout'] = int(args[i + 1])
            except ValueError:
                print(f"Error: Invalid timeout '{args[i + 1]}'", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif arg == '--format':
            if i + 1 >= len(args):
                print("Error: --format requires a value", file=sys.stderr)
                sys.exit(1)
            fmt = args[i + 1]
            if fmt not in ['table', 'markdown', 'json']:
                print(f"Error: Invalid format '{fmt}'. Use: table, markdown, json", file=sys.stderr)
                sys.exit(1)
            config['format'] = fmt
            i += 2
        else:
            print(f"Error: Unknown argument '{arg}'", file=sys.stderr)
            sys.exit(1)

    return config


async def main():
    """Main entry point."""
    config = parse_args(sys.argv[1:])

    client = MultiModelClient(timeout=config['timeout'])

    # For chat mode, use only first model
    if config['mode'] == 'chat':
        models = [config['models'][0]]
    else:
        models = config['models']

    # Execute queries
    responses = await client.query_all(models, config['question'])

    # Format output
    if config['mode'] == 'consensus':
        output = format_consensus(responses)
    elif config['format'] == 'markdown':
        output = format_markdown(responses)
    elif config['format'] == 'json':
        output = format_json(responses)
    else:
        output = format_table(responses, show_full=(config['mode'] == 'chat'))

    print(output)

    # Exit codes
    successful = sum(1 for r in responses if not r.error)
    if successful == 0:
        sys.exit(1)  # All failed
    elif successful < len(responses):
        sys.exit(2)  # Partial success
    else:
        sys.exit(0)  # All succeeded


if __name__ == '__main__':
    asyncio.run(main())
