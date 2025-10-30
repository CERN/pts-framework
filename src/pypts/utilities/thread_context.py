# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

class RuntimeContext:
    _window = None
    _api = None
    _app = None

    @classmethod
    def set(cls, window, api, app):
        cls._window = window
        cls._api = api
        cls._app = app

    @classmethod
    def get_window(cls):
        return cls._window

    @classmethod
    def get_api(cls):
        return cls._api

    @classmethod
    def get_app(cls):
        return cls._app

    @classmethod
    def is_ready(cls):
        return all((cls._window, cls._api, cls._app))


