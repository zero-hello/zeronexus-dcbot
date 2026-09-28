import subprocess
import sys


def test_agent_intelligence_import_order_is_cycle_safe() -> None:
    script = (
        "import zeronexus.intelligence.deep_thinking_controller; "
        "from zeronexus.agent.engine import AgentEngine; "
        "from zeronexus.intelligence.dynamic_projector import DynamicToolProjector; "
        "assert AgentEngine and DynamicToolProjector"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
