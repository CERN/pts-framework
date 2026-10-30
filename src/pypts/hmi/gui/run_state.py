"""
Where the run is, as the GUI window shows it.

One value instead of three hand-synced flags: the status-bar word, the
Start/Resume swap and the actions a run forbids are all derived from it, so
they can never disagree. GUI._set_run_state() is the only writer and renders
every one of them; nothing else may set the field.
"""

from enum import Enum


class RunState(Enum):
    """The member value is the word the status bar shows."""

    #: No run yet, or the recipe was unloaded.
    IDLE = "Idle"
    RUNNING = "Running"
    #: Pause clicked; the hold begins once the current step has finished.
    PAUSING = "Pausing"
    #: The engine confirmed the hold (RunPaused).
    PAUSED = "Paused"
    FINISHED = "Finished"
    STOPPED = "Stopped"

    @property
    def in_progress(self) -> bool:
        """True between RunStarted and RunFinished: loading, restarting and
        engineering mode are off the table while this holds."""
        return self in (RunState.RUNNING, RunState.PAUSING, RunState.PAUSED)

    @property
    def paused(self) -> bool:
        """True from the operator's Pause click until Resume, RunResumed or the
        end of the run: Pause is greyed and Start resumes."""
        return self in (RunState.PAUSING, RunState.PAUSED)
