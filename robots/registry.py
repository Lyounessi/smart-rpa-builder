from robot_framework.registry import Registry, robot_name
from .example_robot import InvoiceChecksRobot


def for_project(project):
    registry = Registry()
    # Explicit trusted implementation. Muse output is not automatically imported.
    if project.name != 'Invoice Checks':
        raise ValueError('No trusted robot registered for this project yet.')
    window = project.windows.get(name='Local robot fixture')
    aliases = {element.name: str(element.pk) for element in window.elements.all()}
    required = {'username', 'password', 'login', 'name', 'submit', 'result'}
    if not required.issubset(aliases):
        raise ValueError('Example captured targets are missing.')
    robot = type('ConfiguredInvoiceChecksRobot', (InvoiceChecksRobot,), {'application': str(window.pk), 'elements': aliases})
    registry.register(robot_name(project.name), robot)
    return registry
