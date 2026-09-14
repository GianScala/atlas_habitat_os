"""Fanning independent read-only queries out over a pool of threads.

A dashboard is a dozen queries that have nothing to say to each other, and a
mission page is two. Run one after another they add up: each panel is a
network round trip to Grafana, so twelve of them took twelve times as long as
one, and the reader waited nearly two seconds to see a window they had already
chosen. Run together they cost about what the slowest one costs.

Threads rather than asyncio because the transport is `requests`, which is
blocking. The point is not CPU work — it is a dozen sockets waiting at once.

ONE POOL FOR THE PROCESS, not one per request. The worker threads are the
things that hold the pooled HTTP connections (`datasource/grafana.py` keeps a
session per thread), so a pool that is discarded after each request throws away
every warm connection with it and the next request pays the handshakes again.

Its width is also the cap on how hard ATLAS leans on Grafana: however many
readers refresh at once, this many queries are in flight, and the rest queue.
Nothing submitted here submits further work of its own, so the queue always
drains and the pool cannot deadlock on itself.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")

# Wide enough for the largest fan-out we have — the dashboard's panel
# catalogue — so a single page is never queued behind itself.
MAX_PARALLEL_QUERIES = 12

_pool = ThreadPoolExecutor(
    max_workers=MAX_PARALLEL_QUERIES,
    thread_name_prefix="atlas-query",
)


def gather(tasks: Iterable[Callable[[], T]]) -> list[T]:
    """Run every task at once; return their results in the order given.

    Order is the caller's, not completion order — a dashboard's panels are
    arranged into groups by their position in the catalogue, and a page whose
    charts rearranged themselves according to which query happened to answer
    first would be unreadable.

    A task that raises re-raises here, from the same call the sequential
    version would have raised from. Callers that need one failure not to take
    the others with it catch inside the task, which is also where they know
    what a failure should be reported as.
    """
    futures = [_pool.submit(task) for task in tasks]
    return [future.result() for future in futures]
