"""dev/agent_cost.py: token use of a session split by the main session and each subagent type."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests._load import load

cost = load("dev/agent_cost.py")


def reply(request, model, out, cache_read=0):
    return {"type": "assistant", "requestId": request,
            "message": {"model": model, "usage": {"input_tokens": 1, "cache_creation_input_tokens": 10,
                                                  "cache_read_input_tokens": cache_read, "output_tokens": out}}}


class AgentCostTest(unittest.TestCase):
    def test_split_by_agent_type(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "s1.jsonl"
            # one reply written as two lines (two content blocks) counts once
            main.write_text("\n".join(json.dumps(x) for x in (reply("r1", "opus", 300), reply("r1", "opus", 300),
                                                              {"type": "user", "message": {"content": "hi"}}, "not json")),
                            encoding="utf-8")
            sub = Path(d) / "s1" / "subagents"
            sub.mkdir(parents=True)
            (sub / "agent-a1.jsonl").write_text(json.dumps(reply("r2", "sonnet", 100, 5)), encoding="utf-8")
            (sub / "agent-a1.meta.json").write_text(json.dumps({"agentType": "phro-search:web-gatherer"}), encoding="utf-8")
            (sub / "agent-a2.jsonl").write_text(json.dumps(reply("r3", "sonnet", 100)), encoding="utf-8")  # no meta file
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cost.main([str(main)])
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[1], "USE\tmain\topus\t1\tinput\t1\tcache-write\t10\tcache-read\t0\toutput\t300\tshare\t60.0%")
        self.assertIn("USE\tphro-search:web-gatherer\tsonnet\t1\tinput\t1\tcache-write\t10\tcache-read\t5\toutput\t100\tshare\t20.0%", lines)
        self.assertIn("USE\tsubagent\tsonnet\t1\tinput\t1\tcache-write\t10\tcache-read\t0\toutput\t100\tshare\t20.0%", lines)
        self.assertEqual(lines[-1], "TOTAL\t3 calls\tinput\t3\tcache-write\t30\tcache-read\t5\toutput\t500")


if __name__ == "__main__":
    unittest.main()
