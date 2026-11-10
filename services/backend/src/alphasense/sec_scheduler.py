"""Independent SEC dispatcher: database intentions only, no provider calls."""

import argparse
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import StoreUnavailable, get_store
from alphasense.runs import RunConflict
from alphasense.sec_schedules import ScheduleConflict, ScheduleStore
from alphasense.worker_session_runtime import WorkerSessionMonitor


def dispatch_once(engine: Engine, batch_size: int = 20) -> int:
    return len(ScheduleStore(engine).dispatch_due(batch_size))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--forever", action="store_true")
    parser.add_argument("--worker-id", default="sec-scheduler-" + uuid4().hex[:12])
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args(argv)
    if (
        not 0.1 <= args.poll_seconds <= 60
        or not 1 <= args.batch_size <= 20
        or not 1 <= len(args.worker_id) <= 128
    ):
        parser.error("Invalid scheduler configuration")
    try:
        store = get_store()
        store.check_ready()
        with WorkerSessionMonitor(
            store.engine, args.worker_id, "sec_scheduler", "forever" if args.forever else "once"
        ) as monitor:
            while True:
                monitor.check()
                dispatched = dispatch_once(store.engine, args.batch_size)
                monitor.check()
                if not args.forever:
                    print(f"Schedule occurrences recorded: {dispatched}")
                    return 0
                monitor.wait(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except (SQLAlchemyError, StoreUnavailable, OSError, ValueError, RunConflict, ScheduleConflict):
        print("SEC scheduler stopped; committed schedule intentions remain durable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
