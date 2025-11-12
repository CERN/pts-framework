"""
This file defines the interface exposed to the core module.

Interface layer is necessary for HMI module specifically, as the framework needs flexibility
when it comes to the front-end. Therefore interface layer is decoupling dependencies.

While the interfaces are not needed for other modules, those were introduced
to keep the cross-module communication similar between modules.
Therefore all modules are:
- exposing an interface (eg. SequencerToCoreInterface - provide what sequencer can run on core module)
- using other modules interfaces (eg. CoreToSequencerInterface)

Interfaces were implemented both ways to explicitly show the direction of communication

Workflow of adding message is explained in module-related message file (eg. SEQUENCER_MESSAGES.py)
"""


