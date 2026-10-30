from .contracts import (BusinessRejection, ExecutionCancelled, Outcome,
                        RowResult, RunResult, RunState)


class BaseRobot:
    email_steps = ()

    def setup(self, ctx):
        pass

    def process(self, ctx, inputs):
        raise NotImplementedError

    def recover(self, ctx, outcome):
        """Override and return True only after restoring a known application state."""
        return False

    def teardown(self, ctx):
        pass

    def finalize(self, ctx):
        """Verify the overall result once after all selected rows succeed."""
        pass

    def execute(self, ctx, rows, options):
        result = RunResult(state=RunState.RUNNING)
        remaining = list(rows)
        setup_attempted = False
        try:
            ctx.emit('run_started')
            ctx.checkpoint()
            setup_attempted = True
            ctx.emit('setup_started')
            self.setup(ctx)
            ctx.emit('setup_completed')
            while remaining:
                ctx.checkpoint()
                row = remaining[0]
                ctx.row, ctx.failed_step = row.reference, None
                ctx.business_succeeded = False
                ctx.outputs = {}
                ctx.emit('row_started')
                try:
                    self.process(ctx, row.values)
                    ctx.checkpoint()
                    outcome = RowResult(row.reference, Outcome.OK, 'Success verified by robot.')
                except BusinessRejection:
                    outcome = RowResult(row.reference, Outcome.NOK, 'Business rejection.', ctx.failed_step)
                except ExecutionCancelled:
                    raise
                except Exception as error:
                    outcome = RowResult(row.reference, Outcome.ERROR, 'Technical execution failure.', ctx.failed_step)
                    if options.stop_on_error:
                        result.primary_error = error
                outcome.business_completed = ctx.business_succeeded or outcome.status == Outcome.OK
                outcome.outputs = dict(ctx.outputs)
                if ctx.business_succeeded and outcome.status != Outcome.OK:
                    outcome.message = 'Business operation completed; a subsequent step failed.'
                ctx.emit('row_finished', result=outcome)
                result.rows.append(outcome)
                remaining.pop(0)
                if outcome.status != Outcome.OK:
                    stop = options.stop_on_error if outcome.status == Outcome.ERROR else options.stop_on_nok
                    if stop:
                        result.state = RunState.FAILED if outcome.status == Outcome.ERROR else RunState.COMPLETED
                        result.message = f'Stopped on {outcome.status} policy.'
                        break
                    if remaining and not self.recover(ctx, outcome):
                        result.state = RunState.FAILED
                        result.message = 'Stopped: robot did not confirm recovery.'
                        break
                ctx.row = None
            else:
                if result.rows and all(item.status == Outcome.OK for item in result.rows):
                    ctx.row = None
                    ctx.finalizing = True
                    ctx.outputs = {}
                    ctx.failed_step = None
                    ctx.checkpoint()
                    ctx.emit('finalization_started')
                    try:
                        self.finalize(ctx)
                        ctx.checkpoint()
                        ctx.emit('finalization_completed')
                    except BaseException as error:
                        ctx.emit('finalization_failed', diagnostic=ctx._failure(error))
                        raise
                    finally:
                        result.outputs = dict(ctx.outputs)
                        ctx.finalizing = False
                result.state = RunState.COMPLETED
        except (ExecutionCancelled, KeyboardInterrupt) as error:
            result.primary_error = error
            result.state, result.message = RunState.CANCELLED, 'Execution cancelled.'
        except Exception as error:
            result.primary_error = error
            result.state, result.message = RunState.FAILED, 'Setup, final verification, recovery, or persistence failed. See technical logs.'
        finally:
            result.unprocessed = [row.reference for row in remaining if not (ctx.business_succeeded and row.reference == ctx.row)]
            ctx.cleaning = True
            ctx.row = None
            if setup_attempted:
                try:
                    ctx.emit('teardown_started')
                except BaseException:
                    result.cleanup_errors.append('Could not persist teardown start.')
                try:
                    self.teardown(ctx)
                except BaseException:
                    result.cleanup_errors.append('Robot teardown failed.')
                else:
                    try:
                        ctx.emit('teardown_completed')
                    except BaseException:
                        result.cleanup_errors.append('Could not persist teardown completion.')
            if result.cleanup_errors and result.state == RunState.COMPLETED:
                result.state = RunState.FAILED
                result.message = 'Robot teardown failed.'
        return result
