from robot_framework.base import BaseRobot
from robot_framework.contracts import BusinessRejection


class InvoiceChecksRobot(BaseRobot):
    """Demo aliases are injected as captured IDs by the trusted registry factory."""
    application = None
    elements = {}

    def setup(self, ctx):
        with ctx.step('login'):
            ctx.navigate(self.application)
            ctx.fill(self.elements['username'], ctx.secrets.get('DEMO_USERNAME'))
            ctx.fill(self.elements['password'], ctx.secrets.get('DEMO_PASSWORD'))
            ctx.click(self.elements['login'])
            ctx.assert_visible(self.elements['name'])

    def process(self, ctx, inputs):
        with ctx.step('enter_invoice'):
            ctx.fill(self.elements['name'], inputs['name'])
            ctx.click(self.elements['submit'])
        with ctx.step('verify_invoice'):
            ctx.assert_visible(self.elements['result'])
            if ctx.read_text(self.elements['result']) != 'Accepted':
                raise BusinessRejection()

    def recover(self, ctx, outcome):
        ctx.assert_visible(self.elements['name'])
        return True

    def teardown(self, ctx):
        # Framework closes the browser even if application cleanup fails.
        pass
