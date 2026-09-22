"""Run the Online-Mind2Web repository's own WebJudge in one process.

`src/run.py` fans its tasks out over `multiprocessing.Process` and hands each worker the live
`OpenaiEngine`. That works where multiprocessing forks and fails where it spawns: macOS pickles the
arguments, and an OpenAI client holds an `_thread.RLock`, so the pool dies before the first task
with `TypeError: cannot pickle '_thread.RLock' object`.

So this calls the repository's own `auto_eval` directly, with the repository's own prompts, score
threshold and label extraction. Nothing about the judgement changes; only the pool around it is
gone. It runs outside this project's environment, so it imports nothing from jev-ra.

The engine is subclassed for one reason, also written down in `README.md`: `OpenaiEngine.generate`
fixes `max_new_tokens` at 512, and for the o4-mini backbone the benchmark asks for, that ceiling
covers the model's reasoning tokens as well as its answer. Measured on one key-point call: 394
completion tokens, 320 of them reasoning. A task that needs a little more comes back with no
content at all, and the judge dies on `NoneType.replace`. The ceiling is raised and an empty answer
is turned into an empty string, which the repository's own extractor scores as a failure.
"""

import argparse
import json
import multiprocessing
import sys
from pathlib import Path

MAX_TOKENS = 4096


def parse(argv=None):
    """The command line, which mirrors the repository's own `src/run.py`."""
    parser = argparse.ArgumentParser(description="WebJudge over one directory of trajectories.")
    parser.add_argument("--repository", required=True, help="the Online-Mind2Web checkout")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--trajectories_dir", required=True)
    parser.add_argument("--api_key", required=True)
    parser.add_argument("--output_path", required=True)
    parser.add_argument("--score_threshold", type=int, default=3)
    return parser.parse_args(argv)


def main(argv=None):
    """Judge every task directory and write the repository's own results file."""
    args = parse(argv)
    sys.path.insert(0, str(Path(args.repository) / "src"))
    import run as harness
    from utils import OpenaiEngine

    class Engine(OpenaiEngine):
        """The repository's engine with room for a reasoning backbone's own tokens."""

        def generate(self, messages, max_new_tokens=MAX_TOKENS, **kwargs):
            """Answer, and hand back an empty string rather than nothing when the model says nothing."""
            return [answer or "" for answer in super().generate(messages, max_new_tokens, **kwargs)]

    tasks = sorted(path.name for path in Path(args.trajectories_dir).iterdir() if path.is_dir())
    print(f"Evaluating {len(tasks)} tasks in total.", flush=True)
    model = Engine(model=args.model, api_key=args.api_key)
    labels = []
    harness.auto_eval(args, tasks, labels, multiprocessing.Lock(), model)
    rate = 100.0 * sum(labels) / len(tasks) if tasks else 0.0
    print(f"The success rate is {rate}.", flush=True)
    print(json.dumps({"tasks": len(tasks), "passed": sum(labels)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
