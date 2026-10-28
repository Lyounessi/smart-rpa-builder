import re


def robot_name(project_name):
    slug = re.sub(r'[^A-Z0-9]+', '_', project_name.upper()).strip('_')
    if not slug:
        raise ValueError('Project name must contain letters or numbers.')
    return 'ROBOT_' + slug


class Registry:
    def __init__(self):
        self._robots = {}

    def register(self, name, robot_class):
        if name in self._robots:
            raise ValueError('Robot name already registered.')
        self._robots[name] = robot_class

    def resolve(self, name):
        try:
            return self._robots[name]
        except KeyError:
            raise ValueError('Unknown robot name.') from None
