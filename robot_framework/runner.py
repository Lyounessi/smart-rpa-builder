from .context import RobotContext
from .contracts import ExecutionCancelled, RunResult, RunState


class Runner:
    def __init__(self, registry, browser, secrets, events, cancellation, *, email=None):
        self.registry, self.browser, self.secrets = registry, browser, secrets
        self.events, self.cancellation = events, cancellation
        self.email = email

    def run(self, robot_name, rows, options, *, input_fields=None):
        robot = self.registry.resolve(robot_name)()
        rows = list(rows)
        ctx = RobotContext(self.browser, self.secrets, self.events, self.cancellation, self.email, options.email_timeout_seconds)
        result = RunResult(state=RunState.FAILED, unprocessed=[row.reference for row in rows])
        try:
            ctx.checkpoint()
            fields = set(input_fields) if input_fields is not None else (set.intersection(*(set(row.values) for row in rows)) if rows else set())
            for specification in robot.email_steps:
                specification.validate(fields)
                for row in rows:
                    specification.render(row.values)
            self.browser.open(options)
            result = robot.execute(ctx, rows, options)
        except (ExecutionCancelled, KeyboardInterrupt) as error:
            result.primary_error = error
            result.state, result.message = RunState.CANCELLED, 'Execution cancelled.'
        except Exception as error:
            result.primary_error = error
            result.message = 'Could not initialize run resources.'
        finally:
            try:
                result.artifacts = self.browser.close() or []
            except BaseException:
                result.cleanup_errors.append('Browser or recording cleanup failed.')
                if result.state == RunState.COMPLETED:
                    result.state = RunState.FAILED
            kind = {RunState.COMPLETED: 'run_completed', RunState.CANCELLED: 'run_cancelled'}.get(result.state, 'run_failed')
            self.events.emit(kind, summary=result)
        return result
