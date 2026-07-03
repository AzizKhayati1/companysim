"""Command-line entry point.

Usage:

    companysim demo --headcount 200 --ticks 30
"""
from __future__ import annotations

import argparse
import sys

from companysim.data.generators import GeneratorConfig, WorkforceGenerator
from companysim.model.organization import OrganizationModel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="companysim")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Generate an org and run a short simulation.")
    demo.add_argument("--headcount", type=int, default=200)
    demo.add_argument("--ticks", type=int, default=30)
    demo.add_argument("--seed", type=int, default=42)

    args = parser.parse_args(argv)

    if args.command == "demo":
        return _run_demo(args.headcount, args.ticks, args.seed)
    return 1


def _run_demo(headcount: int, ticks: int, seed: int) -> int:
    gen = WorkforceGenerator(GeneratorConfig(headcount=headcount, seed=seed))
    org = gen.generate()
    print(f"Generated org: {org.name}")
    print(f"  departments: {len(org.departments)}")
    print(f"  teams:       {len(org.teams)}")
    print(f"  employees:   {org.headcount()}")

    model = OrganizationModel(org, seed=seed)
    history = model.run(ticks)

    print()
    print(f"Ran {ticks} ticks.")
    print(history.tail(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
