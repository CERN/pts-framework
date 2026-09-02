# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The step types: the unit of work a sequence is made of.

A step is a class. `steptype:` in the YAML names it - `PythonModule`, `Wait`;
the class names keep a Step suffix but the YAML names drop it - the rest of
the step's YAML keys become its constructor arguments, and its `_step()`
does the work. What each type requires and what is optional is declared in
pypts.recipe.rules, the one importable source for the recipe format.
The base class owns everything that is the same for all of them:

    resolve inputs  ->  _step()  ->  judge outputs  ->  StepResult

Who owns what in this package:

    step.py                the base Step and its lifecycle, StepResult,
                           run_steps() (the sequence-body policy) and
                           run_sequence() (one sequence, steps then
                           teardown-in-finally)
    wait_step.py           WaitStep
    python_module_step.py  a minimal PythonModuleStep (method calls only;
                           module beside the recipe or a dotted import) and
                           load_python_module()
    registry.py            steptype name -> class, and build_step(); the
                           replacement for the old eval() factory
    indexed_step.py        `steptype: Indexed`: one authored step and N
                           parameter sets expanded, at load time, into N
                           ordinary steps. Never reaches the registry
    runtime.py             the execution context: the run's globals and the
                           three seams the Sequencer fills in (emit,
                           should_stop, ask)

Each concrete step type gets a module of its own, named after the class
(snake_case, keeping the class's Step suffix). A newly ported type follows
the same schema: its own file here, plus its registry entry.

The emission model: a step emits its own StepStarted/StepFinished through
`Runtime.emit`, and run_sequence() emits SequenceStarted/SequenceFinished the
same way - so when SequenceStep lands, a nested sequence reports through the
channel it already holds. The Sequencer provides `emit` (its outbox's send)
and owns the run-level pair, RunStarted/RunFinished. Nothing in this package
imports a queue, a QueueWrapper or the Sequencer: a bare `Runtime()` is a
complete fake context, which is what keeps every step testable stand-alone.

`inputs` says where each argument comes from - a bare value is the
literal itself, and a mapping reads a `global`. `outputs` says what to
do with each key of the dict the step returned: judge it (`passfail`,
`equals`, `range`), mark it not-a-measurement (`pass`) or store it in a
`global`. A step
that returns a non-dict has it wrapped as {"output": value}; None becomes
{}. There is no type coercion anywhere - '45' is a string and 45 is an int.
When several entries judge, the last one wins - kept from the old engine for
parity; revisiting it is a roadmap TODO (F6).

Errors: a step failure must become a StepResult with ResultType.ERROR and
the traceback, never a silent continue - `run()` is the one place that
catches broadly, because turning the exception into data is its job. Only
ERROR stops a sequence; a FAIL (a failed measurement) never halts anything.

Which of the old engine's ten types are being ported, which are dropped, and
what each port still needs is the catalogue in step.md beside this file - read
it before starting one. In short: the rest of PythonModuleStep
(read_attribute/write_attribute) and three interactive types
(UserInteraction, UserWrite, UserLoading) are to come; UserRunMethodStep and
SequenceStep are dropped; IndexedStep came back as `Indexed`, expanded at load
time rather than looped at run time; and the SSH pair leaves the step layer to
become part of the framework. The continue_on_error policy (F8:
three disagreeing sources of truth in the old engine) is to be resolved in
recipe parsing, defaulting to True. Every old type's YAML is documented in
section 10 of resources/roadmap/recipe_guide.md.
"""
