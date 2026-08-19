# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The step types: the unit of work a sequence is made of.

A step is a class. `steptype:` in the YAML names it, the rest of the step's
YAML keys become its constructor arguments, and its `_step()` does the work.
The base class owns everything that is the same for all of them:

    resolve inputs  ->  _step()  ->  judge outputs  ->  StepResult

Who owns what in this package:

    step.py      the base Step and its lifecycle, StepResult, run_steps()
                 (the sequence-body policy) and run_sequence() (one sequence,
                 steps then teardown-in-finally)
    steps.py     the concrete step types - WaitStep, and a minimal
                 PythonModuleStep (method calls only; module beside the recipe
                 or a dotted import)
    registry.py  steptype name -> class, and build_step(); the replacement
                 for the old eval() factory
    runtime.py   the execution context: globals, the locals stack, and the
                 two seams the Sequencer fills in (emit, should_stop)

The emission model: a step emits its own StepStarted/StepFinished through
`Runtime.emit`, and run_sequence() emits SequenceStarted/SequenceFinished the
same way - so when SequenceStep lands, a nested sequence reports through the
channel it already holds. The Sequencer provides `emit` (its outbox's send)
and owns the run-level pair, RunStarted/RunFinished. Nothing in this package
imports a queue, a QueueWrapper or the Sequencer: a bare `Runtime()` is a
complete fake context, which is what keeps every step testable stand-alone.

`input_mapping` says where each argument comes from - `direct` (a literal
from the YAML, the default), `local` or `global`. `output_mapping` says what
to do with each key of the dict the step returned: judge it (`passfail`,
`equals`, `range`, `passthrough`) or store it (`local`, `global`). A step
that returns a non-dict has it wrapped as {"output": value}; None becomes
{}. There is no type coercion anywhere - '45' is a string and 45 is an int.
When several entries judge, the last one wins - kept from the old engine for
parity; revisiting it is a roadmap TODO (F6).

Errors: a step failure must become a StepResult with ResultType.ERROR and
the traceback, never a silent continue - `run()` is the one place that
catches broadly, because turning the exception into data is its job. Only
ERROR stops a sequence; a FAIL (a failed measurement) never halts anything.

Still in old_code/steps.py, ported as their dependencies land: the rest of
PythonModuleStep (read_attribute/write_attribute, the rglob module search),
the four User* types (the request/response prompt wiring in
messages/run_events.py), SequenceStep and IndexedStep (nesting),
SSHConnectStep/SSHCloseStep (credentials move to the Config Handler first).
The continue_on_error policy machinery (F8: three disagreeing sources of
truth in the old engine) is deliberately not ported yet - see the roadmap.
Every type's YAML is documented in section 10 of
resources/roadmap/recipe_guide.md.
"""
