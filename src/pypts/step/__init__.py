# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The step types: the unit of work a sequence is made of.

Empty - ported in roadmap Phase 1 alongside `pypts.recipe`. The working
originals are `old_code/steps.py` with the base `Step` in `old_code/recipe.py`
(both files are entirely commented out), and every type is documented with its
YAML in section 10 of `resources/roadmap/recipe_guide.md`.

The shape
---------
A step is a class. `steptype:` in the YAML names it, the rest of the step's YAML
keys become its constructor arguments, and its `_step()` does the work. The base
class owns everything that is the same for all of them:

    resolve inputs  ->  _step()  ->  judge outputs  ->  StepResult

`input_mapping` says where each argument comes from - `direct` (a literal from
the YAML), `local` or `global`. `output_mapping` says what to do with each key
of the dict the step returned: judge it (`passfail`, `equals`, `range`,
`passthrough`) or store it (`local`, `global`). A step that returns a non-dict
has it wrapped as `{"output": value}`; `None` becomes `{}`. There is no type
coercion anywhere - `value: '45'` is a string and `value: 45` is an int.

Every step also carries `step_name`, `description`, an optional stable `id`,
`skip` and `critical`.

The ten types
-------------
    PythonModuleStep     import a module from the test package and call a method
    WaitStep             sleep
    SequenceStep         call another sequence by name
    UserInteractionStep  show a message and buttons, wait for a choice
    UserLoadingStep      let the operator pick a file
    UserRunMethodStep    prompt, then run a method
    UserWriteStep        let the operator type a value, or configure a serial port
    SSHConnectStep       open a paramiko session, publish it as a global
    SSHCloseStep         close it - put it in teardown_steps, the only block
                         guaranteed to run
    IndexedStep          never written by hand: synthesised when an input carries
                         `indexed: true`, and runs the wrapped step once per element

Error control
-------------
Only `ERROR` stops a sequence. A `FAIL` - a failed measurement - never halts
anything, which is intended (a failing unit should still be fully characterised)
and surprises everyone who meets it. `critical: true` re-arms the stop even when
continuing is enabled, and `globals.continue_on_error` overrides every per-step
setting.

A step failure has to reach a `StepResult` rather than being swallowed, so this
layer is `@report_and_reraise()` territory - not `@catch_and_report_errors()`,
which is for event loops. See roadmap section 1.10.

What the port has to change
---------------------------
- **The four interactive types cannot work as they stand.** Each one puts a live
  `queue.SimpleQueue` inside an event to reach the operator (`steps.py:552, 736,
  822, 947`, and the serial-number prompt in `recipe.py:442`). The HMI is a
  separate process now, so that queue cannot be pickled. The replacement is
  already declared and already handled at the receiving end:
  `UserPromptRequest`/`UserPromptResponse` and the serial-number pair in
  `messages/run_events.py`, joined by a `request_id`, with the waiting half in
  `messages/blocking_messages.py`. A step calls `PendingRequests.wait()` on the
  sequence worker thread - never on the thread draining the inbox, or it
  deadlocks.
- `SSHConnectStep` publishes a live paramiko client as the global `ssh_client`
  for later steps to take as an input. That works only because everything is one
  thread today; it does not cross a process boundary either.
- `continue_on_error` **leaks forward**: the types that do not set it
  (`WaitStep`, `SequenceStep`, `IndexedStep`) leave the previous step's value in
  place.
- `steptype` matching is case-insensitive for eight types and case-sensitive for
  the two SSH ones.
- The last judging entry in an `output_mapping` wins, rather than all of them
  having to pass - the opposite of what the old documentation claims.
"""
