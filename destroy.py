"""Tear down a mineru-runpod endpoint and (optionally) its template.

Reads RUNPOD_ENDPOINT_ID + MINERU_TEMPLATE_ID from environment / .env, or
takes them on the CLI.

Deletion goes through RunPod's REST API rather than the Python SDK, because the
SDK has no delete call for either resource — see runpod_rest.py. This script used
to look one up defensively and, finding nothing, print "delete via dashboard" to
stderr and return 0. A teardown that exits successfully having deleted nothing is
one a CI job believes, while the endpoint keeps billing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import runpod_rest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint-id",
        default=os.environ.get("RUNPOD_ENDPOINT_ID"),
    )
    parser.add_argument(
        "--template-id",
        default=os.environ.get("MINERU_TEMPLATE_ID"),
    )
    parser.add_argument(
        "--keep-template",
        action="store_true",
        help="Only delete the endpoint; leave the template registered.",
    )
    args = parser.parse_args()

    api_key = (os.environ.get("RUNPOD_API_KEY") or "").strip()
    if not api_key:
        print("RUNPOD_API_KEY is not set.", file=sys.stderr)
        return 2

    if args.endpoint_id:
        print(f"Scaling endpoint {args.endpoint_id} to 0 workers and deleting …")
        try:
            # Both bounds to zero first. RunPod documents that as the precondition
            # for deleting an endpoint, and the line above has claimed to do it
            # since this script was written — it never did.
            runpod_rest.scale_to_zero(args.endpoint_id, api_key=api_key)
            runpod_rest.delete_endpoint(args.endpoint_id, api_key=api_key)
        except runpod_rest.RunpodApiError as e:
            # Loud, and non-zero. This used to print to stderr and `return 0`,
            # so a CI teardown read success while the endpoint kept billing.
            print(
                f"error: endpoint {args.endpoint_id} was NOT deleted: {e}",
                file=sys.stderr,
            )
            print(
                "  delete it in the RunPod console before it accrues more cost.",
                file=sys.stderr,
            )
            return 1
        print(f"  endpoint {args.endpoint_id} deleted")

    if args.template_id and not args.keep_template:
        print(f"Deleting template {args.template_id} …")
        try:
            runpod_rest.delete_template(args.template_id, api_key=api_key)
        except runpod_rest.RunpodApiError as e:
            print(
                f"error: template {args.template_id} was NOT deleted: {e}",
                file=sys.stderr,
            )
            return 1
        print(f"  template {args.template_id} deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
