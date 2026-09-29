"""Durable-execution loop. Kept free of the SDK so tests can drive it."""

SLICE_NAMES = ("slice-1", "slice-2", "slice-3", "slice-4")
# A finished slice has to leave the invocation. The next slice then starts
# with a fresh 15-minute budget instead of the few minutes left after this one.
_YIELD_SECONDS = 1


def run_workflow(user_id: str, request_id: str, step, wait, slice_fn, on_failed) -> str:
    """Run at most four slices.

    `step(name, fn)` checkpoints `fn`. `wait(name, seconds)` suspends.
    `slice_fn(index)` returns `{done, wait_seconds, cursor_moved}`.
    """
    for index, name in enumerate(SLICE_NAMES):
        result = step(name, lambda index=index: slice_fn(index))
        if result["done"]:
            return "completed"
        if result["wait_seconds"]:
            wait(f"wait-after-{name}", result["wait_seconds"])
            continue
        if not result["cursor_moved"]:
            on_failed()
            return "failed"
        if index < len(SLICE_NAMES) - 1:
            wait(f"yield-after-{name}", _YIELD_SECONDS)
    on_failed()
    return "failed"
