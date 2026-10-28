from .context import RobotContext
from .contracts import ExecutionCancelled, RunResult, RunState


class Runner:
    def __init__(self, registry, browser, secrets, events, cancellation):
        self.registry, self.browser, self.secrets = registry, browser, secrets
        self.events, self.cancellation = events, cancellation

    def run(self, robot_name, rows, options):
        robot = self.registry.resolve(robot_name)()
        rows = list(rows)
        ctx = RobotContext(self.browser, self.secrets, self.events, self.cancellation)
        result = RunResult(state=RunState.FAILED, unprocessed=[row.reference for row in rows])
        try:
            ctx.checkpoint()
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
