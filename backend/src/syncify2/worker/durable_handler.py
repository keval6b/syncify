import time

from aws_durable_execution_sdk_python import DurableContext, durable_execution
from aws_durable_execution_sdk_python.config import Duration

from syncify2.common import db
from syncify2.worker.slice_runner import _SLICE_SECONDS, run_slice
from syncify2.worker.workflow import run_workflow

_RETURN_BUFFER_SECONDS = 60


@durable_execution
def handler(event: dict, context: DurableContext):
    user_id = event["user_id"]
    request_id = event["request_id"]
    arn = context.execution_context.durable_execution_arn
    if arn:
        db.set_execution_arn(user_id, request_id, arn)

    def step(name, fn):
        return context.step(lambda _ctx, fn=fn: fn(), name=name)

    def wait(name, seconds):
        context.wait(Duration.from_seconds(max(1, int(seconds))), name=name)

    def slice_fn(index):
        remaining = _SLICE_SECONDS + _RETURN_BUFFER_SECONDS
        lambda_context = context.lambda_context
        if lambda_context is not None:
            remaining = lambda_context.get_remaining_time_in_millis() / 1000
        budget = min(_SLICE_SECONDS, max(1, remaining - _RETURN_BUFFER_SECONDS))
        return run_slice(
            user_id,
            request_id,
            index,
            deadline=time.monotonic() + budget,
        ).as_dict()

    def on_failed():
        db.mark_request_failed(user_id, request_id)

    try:
        return run_workflow(user_id, request_id, step, wait, slice_fn, on_failed)
    except Exception:
        db.mark_request_failed(user_id, request_id)
        raise
