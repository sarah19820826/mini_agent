"""
Personal Agent MVP - From 0 to 1

A minimal agent system based on ReAct loop with memory, tools, skills,
sub-agent delegation, context compression, and error recovery.

Usage:
    python main.py

Reference: Agent.md (阿里技术)
"""
import sys
import os

# Fix Windows console UTF-8 encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env file
def load_dotenv(path=None):
    """Parse .env file and set environment variables."""
    env_path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()


load_dotenv()

from config.settings import *
from agent.agent import IdleAgent
from utils.llm_client import SimpleLLMClient


def main():
    llm = SimpleLLMClient(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
    )
    agent = IdleAgent(llm=llm, max_iterations=MAX_ITERATIONS)

    print("Agent started. Type 'quit' to exit.")
    for user_input in iter(input("\nYou: "), "quit"):
        try:
            result = agent.run_sync(user_input)
            print(f"\nAgent: {result.get('final_answer', '(no answer)')}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    main()
