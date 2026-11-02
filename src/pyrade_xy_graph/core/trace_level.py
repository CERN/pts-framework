"""
Registers a TRACE logging level (below DEBUG) and Logger.trace(), as a
side effect of import. Qt-free so core/ modules can use log.trace()
without depending on ui/log_panel.py being imported first.
"""
import logging

TRACE = 5
logging.addLevelName(TRACE, 'TRACE')

if not hasattr(logging.Logger, 'trace'):
    def _trace(self, message, *args, **kwargs):
        if self.isEnabledFor(TRACE):
            self._log(TRACE, message, args, **kwargs)

    logging.Logger.trace = _trace
