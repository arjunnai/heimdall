from __future__ import annotations

import argparse
import json

from app.agent import IncidentAgent
from app.config import get_settings
from app.data import FixtureDataStore, PostgresDataStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigate an incident with Heimdall")
    parser.add_argument("description")
    parser.add_argument("--seed", help="Use a deterministic fixture instead of Postgres")
    parser.add_argument("--variant", default="guarded")
    args = parser.parse_args()
    datastore = (
        FixtureDataStore(args.seed) if args.seed else PostgresDataStore(get_settings().database_url)
    )
    result = IncidentAgent(datastore, prompt_variant=args.variant).investigate(args.description)
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
