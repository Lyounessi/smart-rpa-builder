from robot_framework.email import EmailStep
from .example_robot import InvoiceChecksRobot


class InvoiceChecksEmailRobot(InvoiceChecksRobot):
    notification = EmailStep(
        step_id='notify_supplier', account='notifications', to='{{email}}',
        subject='Supplier {{name}} created', body='Your supplier registration is complete.')
    email_steps = (notification,)

    def process(self, ctx, inputs):
        super().process(ctx, inputs)
        # A durable boundary: notification failure must never repeat this operation.
        ctx.business_completed()
        ctx.email.send_step(self.notification, inputs)
