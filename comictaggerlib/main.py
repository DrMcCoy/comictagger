"""A python app to (automatically) tag comic archives"""
#
# Copyright 2012-2014 ComicTagger Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import argparse
import json
import locale
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
from typing import cast

import settngs

import comicapi.comicarchive
import comicapi.utils
import comictalker
from comictaggerlib import cli, ctsettings
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.ctversion import version
from comictaggerlib.log import setup_logging

if sys.version_info < (3, 10):
    import importlib_metadata
else:
    import importlib.metadata as importlib_metadata

logger = logging.getLogger("comictagger")


logger.setLevel(logging.DEBUG)


def _lang_code_mac() -> str:
    """
    stolen from https://github.com/mu-editor/mu
    Returns the user's language preference as defined in the Language & Region
    preference pane in macOS's System Preferences.
    """

    # Uses the shell command `defaults read -g AppleLocale` that prints out a
    # language code to standard output. Assumptions about the command:
    # - It exists and is in the shell's PATH.
    # - It accepts those arguments.
    # - It returns a usable language code.
    #
    # Reference documentation:
    # - The man page for the `defaults` command on macOS.
    # - The macOS underlying API:
    #   https://developer.apple.com/documentation/foundation/nsuserdefaults.

    lang_detect_command = "defaults read -g AppleLocale"

    status, output = subprocess.getstatusoutput(lang_detect_command)
    if status == 0:
        # Command was successful.
        lang_code = output
    else:
        logging.warning("Language detection command failed: %r", output)
        lang_code = ""

    return lang_code


def configure_locale() -> None:
    if sys.platform == "darwin" and "LANG" not in os.environ:
        code = _lang_code_mac()
        if code != "":
            os.environ["LANG"] = f"{code}.utf-8"

    locale.setlocale(locale.LC_ALL, "")
    sys.stdout.reconfigure(encoding=sys.getdefaultencoding())  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding=sys.getdefaultencoding())  # type: ignore[attr-defined]
    sys.stdin.reconfigure(encoding=sys.getdefaultencoding())  # type: ignore[attr-defined]


def update_publishers(config: settngs.Config[ct_ns]) -> None:
    json_file = config[0].Runtime_Options__config.user_config_dir / "publishers.json"
    if json_file.exists():
        try:
            comicapi.utils.update_publishers(json.loads(json_file.read_text("utf-8")))
        except Exception as e:
            logger.exception("Failed to load publishers from %s: %s", json_file, e)


class App:
    """docstring for App"""

    def __init__(self) -> None:
        self.config: settngs.Config[ct_ns]
        self.initial_arg_parser = ctsettings.initial_commandline_parser()
        self.config_load_success = False

    def run(self) -> None:
        configure_locale()
        conf = self.initialize()
        self.initialize_dirs(conf.config)
        self.load_plugins(conf)
        self.register_settings()
        self.config = self.parse_settings(conf.config)

        self.main()

    def load_plugins(self, opts: argparse.Namespace) -> None:
        comicapi.comicarchive.load_archive_plugins()
        ctsettings.talkers = comictalker.get_talkers(version, opts.config.user_cache_dir)

    def list_plugins(
        self, talkers: list[comictalker.ComicTalker], archivers: list[type[comicapi.comicarchive.Archiver]]
    ) -> None:
        print("Metadata Sources: (ID: Name URL)")  # noqa: T201
        for talker in talkers:
            print(f"{talker.id}: {talker.name} {talker.default_api_url}")  # noqa: T201

        print("\nComic Archive: (Name: extension, exe)")  # noqa: T201
        for archiver in archivers:
            a = archiver()
            print(f"{a.name()}: {a.extension()}, {a.exe}")  # noqa: T201

    def initialize(self) -> argparse.Namespace:
        conf, _ = self.initial_arg_parser.parse_known_args()
        assert conf is not None
        setup_logging(conf.verbose, conf.config.user_log_dir)
        return conf

    def register_settings(self) -> None:
        self.manager = settngs.Manager(
            "A utility for reading and writing metadata to comic archives.\n\n\n"
            + "If no options are given, %(prog)s will run in windowed mode.",
            "For more help visit the wiki at: https://github.com/comictagger/comictagger/wiki",
        )
        ctsettings.register_commandline_settings(self.manager)
        ctsettings.register_file_settings(self.manager)
        ctsettings.register_plugin_settings(self.manager)

    def parse_settings(self, config_paths: ctsettings.ComicTaggerPaths, *args: str) -> settngs.Config[ct_ns]:
        cfg, self.config_load_success = ctsettings.parse_config(
            self.manager, config_paths.user_config_dir / "settings.json", list(args) or None
        )
        config = cast(settngs.Config[ct_ns], self.manager.get_namespace(cfg, file=True, cmdline=True))
        config[0].Runtime_Options__config = config_paths

        config = ctsettings.validate_commandline_settings(config, self.manager)
        config = ctsettings.validate_file_settings(config)
        config = ctsettings.validate_plugin_settings(config)
        return config

    def initialize_dirs(self, paths: ctsettings.ComicTaggerPaths) -> None:
        paths.user_data_dir.mkdir(parents=True, exist_ok=True)
        paths.user_config_dir.mkdir(parents=True, exist_ok=True)
        paths.user_cache_dir.mkdir(parents=True, exist_ok=True)
        paths.user_state_dir.mkdir(parents=True, exist_ok=True)
        paths.user_log_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("user_data_dir: %s", paths.user_data_dir)
        logger.debug("user_config_dir: %s", paths.user_config_dir)
        logger.debug("user_cache_dir: %s", paths.user_cache_dir)
        logger.debug("user_state_dir: %s", paths.user_state_dir)
        logger.debug("user_log_dir: %s", paths.user_log_dir)

    def main(self) -> None:
        assert self.config is not None
        # config already loaded
        error = None

        talkers = ctsettings.talkers
        del ctsettings.talkers

        if len(talkers) < 1:
            error = error = (
                "Failed to load any talkers, please re-install and check the log located in '"
                + str(self.config[0].Runtime_Options__config.user_log_dir)
                + "' for more details",
                True,
            )

        signal.signal(signal.SIGINT, signal.SIG_DFL)

        logger.debug("Installed Packages")
        for pkg in sorted(importlib_metadata.distributions(), key=lambda x: x.name):
            logger.debug("%s\t%s", pkg.metadata["Name"], pkg.metadata["Version"])

        comicapi.utils.load_publishers()
        update_publishers(self.config)

        if self.config[0].Commands__list_plugins:
            self.list_plugins(list(talkers.values()), comicapi.comicarchive.archivers)
            return

        if self.config[0].Commands__only_save_config:
            if self.config_load_success:
                settings_path = self.config[0].Runtime_Options__config.user_config_dir / "settings.json"
                if self.config_load_success:
                    ctsettings.save_file(self.config, settings_path)
                print("Settings saved")  # noqa: T201
                return

        if not self.config_load_success:
            error = (
                "Failed to load settings, check the log located in '"
                + str(self.config[0].Runtime_Options__config.user_log_dir)
                + "' for more details",
                True,
            )

        if not self.config[0].Runtime_Options__no_gui:
            try:
                from comictaggerlib import gui

                if not gui.qt_available:
                    raise gui.import_error
                return gui.open_tagger_window(talkers, self.config, error)
            except ImportError:
                self.config[0].Runtime_Options__no_gui = True
                logger.warning("PyQt5 is not available. ComicTagger is limited to command-line mode.")

        # GUI mode is not available or CLI mode was requested
        if error and error[1]:
            print(f"A fatal error occurred please check the log for more information: {error[0]}")  # noqa: T201
            raise SystemExit(1)
        try:
            cli.CLI(self.config[0], talkers).run()
        except Exception:
            logger.exception("CLI mode failed")


def main() -> None:
    App().run()
