# Smart RPA Builder — Powered by Muse

Smart RPA Builder is a web platform designed to help businesses and individuals create robots that automate repetitive work without writing code.

Users will define workflows through screenshots, captured interface elements, and short step-by-step instructions. Meta Muse will use this context to generate robots that run through a Python automation framework.

The planned platform will support inspecting web and Windows desktop applications, running robots, reviewing execution logs, and refining workflows.

> **Status:** Early development. The capabilities described below are planned and will be documented as they become available.

## First Component: Inspector Tool

The inspector will help users capture the interface elements required for an automation, such as fields, buttons, and menus.

Each captured element will be saved with its locator, screenshot, and metadata, and linked to a project in the database. Users will reference these elements when describing workflow steps.

Muse will use the captured elements, workflow instructions, and framework documentation to build the robot.

## Hackathon Contributions

This project is being built during the hackathon, from October 26 to November 4, 2026. Implemented features and setup instructions will be added as development progresses.

## License

This project is licensed under the [MIT License](LICENSE).
