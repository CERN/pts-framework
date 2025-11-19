# pypts

## Overview

This framework orchestrates automation and monitoring tasks by running separate modules as independent processes. It is built for extensibility, reliability, and clear communication between modules using well-structured message patterns.

## Architecture

### Launcher

- Startup logic creates all required inter-process queues and launches top-level modules—CORE and either a GUI or CLI HMI, based on command-line options.

### CORE

- Serves as the coordinator, responsible for spawning and managing secondary modules (Sequencer and Report), and handling system-wide event processing.

### HMI (GUI/CLI)

- Provides a user interface and sends user commands to the CORE.

### Sequencer

- Runs operational sequences as instructed by the CORE, reporting progress and results.

### Report

- Generates and exports process or experiment reports, reacting to commands from the CORE.

All modules are run in separate processes to maximize resilience and parallelism.

## Communication Model

All interaction between modules happens through Python’s multiprocessing.Queue, but never with direct queue access. Instead, each queue is wrapped in a typed interface class. This abstraction ensures:

- Communication is strictly structured and type-safe.
- Module dependencies are minimized, making it easy to swap out or refactor parts of the system.
- Messages sent between modules are always explicit objects, typically enums for commands and dataclasses for events, and are defined in dedicated message files for each module.

## Interface and Message Principles

- Interfaces define the exact actions a module presents to others, ensuring clear and stable contracts for interaction.
- Data-layer classes implement these interfaces, performing the actual queue operations for sending and receiving messages.
- Extending the protocol is straightforward: add new messages in the relevant message file, extend the interface, and process the new message type in the relevant event handler.
- This pattern provides clarity about communication flow and enables future extensions without breaking compatibility.

## Adding or Extending Modules

To add new messages or module interactions:

1. Define a new command or event in the corresponding message file.
2. Extend the relevant interface with a new method.
3. Implement that method in the associated data-layer class.
4. Handle the new message in the recipient module’s event loop.

This workflow keeps all communication robust, clear, and well-documented within the codebase.

## Key Features

- Each core element (HMI, CORE, Sequencer, Report) is a fully independent process.
- All inter-process interactions are type-safe and explicitly modeled.
- Flexible user interface: switch between CLI and GUI at runtime.
- Clear patterns for extension and maintenance.
- Explicit, easily auditable communication patterns.

## License

Copyright CERN, 2025  
Licensed under LGPL-2.1-or-later
