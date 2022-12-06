"""A PyQT4 dialog to enter app settings"""
#
# Copyright 2012-2014 Anthony Beville
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

import html
import logging
import os
import pathlib
import platform

from PyQt5 import QtCore, QtGui, QtWidgets, uic

from comicapi import utils
from comicapi.genericmetadata import md_test
from comictaggerlib import settings
from comictaggerlib.ctversion import version
from comictaggerlib.filerenamer import FileRenamer
from comictaggerlib.imagefetcher import ImageFetcher
from comictaggerlib.ui import ui_path
from comictalker.comiccacher import ComicCacher
from comictalker.talkerbase import ComicTalker

logger = logging.getLogger(__name__)

windowsRarHelp = """
                <html><head/><body><p>To write to CBR/RAR archives,
                you will need to have the tools from
                <span style=" text-decoration: underline; color:#0000ff;">
                <a href="http://www.win-rar.com/download.html">WINRar</a></span>
                installed. (ComicTagger only uses the command-line rar tool.)
                </p></body></html>
                """

linuxRarHelp = """
                <html><head/><body><p>To write to CBR/RAR archives,
                you will need to have the shareware rar tool from RARLab installed.
                Your package manager should have rar (e.g. "apt-get install rar"). If not, download it
                <span style=" text-decoration: underline; color:#0000ff;">
                <a href="https://www.rarlab.com/download.htm">here</a></span>,
                and install in your path. </p></body></html>
                """

macRarHelp = """
                <html><head/><body><p>To write to CBR/RAR archives,
                you will need the rar tool.  The easiest way to get this is
                to install <span style=" text-decoration: underline; color:#0000ff;">
                <a href="https://brew.sh/">homebrew</a></span>.
                </p>Once homebrew is installed, run: <b>brew install caskroom/cask/rar</b></body></html>
                """


template_tooltip = """
The template for the new filename. Uses python format strings https://docs.python.org/3/library/string.html#format-string-syntax
Accepts the following variables:
{is_empty}         (boolean)
{tag_origin}       (string)
{series}           (string)
{issue}            (string)
{title}            (string)
{publisher}        (string)
{month}            (integer)
{year}             (integer)
{day}              (integer)
{issue_count}      (integer)
{volume}           (integer)
{genre}            (string)
{language}         (string)
{comments}         (string)
{volume_count}     (integer)
{critical_rating}  (float)
{country}          (string)
{alternate_series} (string)
{alternate_number} (string)
{alternate_count}  (integer)
{imprint}          (string)
{notes}            (string)
{web_link}         (string)
{format}           (string)
{manga}            (string)
{black_and_white}  (boolean)
{page_count}       (integer)
{maturity_rating}  (string)
{story_arc}        (string)
{series_group}     (string)
{scan_info}        (string)
{characters}       (string)
{teams}            (string)
{locations}        (string)
{credits}          (list of dict({'role': string, 'person': string, 'primary': boolean}))
{writer}           (string)
{penciller}        (string)
{inker}            (string)
{colorist}         (string)
{letterer}         (string)
{cover artist}     (string)
{editor}           (string)
{tags}             (list of str)
{pages}            (list of dict({'Image': string(int), 'Type': string, 'Bookmark': string, 'DoublePage': boolean}))

CoMet-only items:
{price}            (float)
{is_version_of}    (string)
{rights}           (string)
{identifier}       (string)
{last_mark}        (string)
{cover_image}      (string)

Examples:

{series} {issue} ({year})
Spider-Geddon 1 (2018)

{series} #{issue} - {title}
Spider-Geddon #1 - New Players; Check In
"""


class SettingsWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget, options: settings.OptionValues, talker_api: ComicTalker) -> None:
        super().__init__(parent)

        uic.loadUi(ui_path / "settingswindow.ui", self)

        self.setWindowFlags(
            QtCore.Qt.WindowType(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)
        )

        self.options = options
        self.talker_api = talker_api
        self.name = "Settings"

        if platform.system() == "Windows":
            self.lblRarHelp.setText(windowsRarHelp)

        elif platform.system() == "Linux":
            self.lblRarHelp.setText(linuxRarHelp)

        elif platform.system() == "Darwin":
            self.leRarExePath.setReadOnly(False)

            self.lblRarHelp.setText(macRarHelp)
            self.name = "Preferences"

        self.setWindowTitle("ComicTagger " + self.name)
        self.lblDefaultSettings.setText("Revert to default " + self.name.casefold())
        self.btnResetSettings.setText("Default " + self.name)

        nmit_tip = """<html>The <b>Name Match Ratio Threshold: Auto-Identify</b> is for eliminating automatic
                search matches that are too long compared to your series name search. The lower
                it is, the more likely to have a good match, but each search will take longer and
                use more bandwidth. Too high, and only the very closest matches will be explored.</html>"""
        nmst_tip = """<html>The <b>Name Match Ratio Threshold: Search</b> is for reducing the total
                number of results that are returned from a search. The lower it is, the more pages will
                be returned (max 5 pages or 500 results)</html>"""

        self.sbNameMatchIdentifyThresh.setToolTip(nmit_tip)
        self.sbNameMatchSearchThresh.setToolTip(nmst_tip)

        pbl_tip = """<html>
            The <b>Publisher Filter</b> is for eliminating automatic matches to certain publishers
            that you know are incorrect. Useful for avoiding international re-prints with same
            covers or series names. Enter publisher names separated by commas.
            </html>"""
        self.tePublisherFilter.setToolTip(pbl_tip)

        validator = QtGui.QIntValidator(1, 4, self)
        self.leIssueNumPadding.setValidator(validator)

        self.leRenameTemplate.setToolTip(f"<pre>{html.escape(template_tooltip)}</pre>")
        self.settings_to_form()
        self.rename_error: Exception | None = None
        self.rename_test()
        self.dir_test()

        self.btnBrowseRar.clicked.connect(self.select_rar)
        self.btnClearCache.clicked.connect(self.clear_cache)
        self.btnResetSettings.clicked.connect(self.reset_settings)
        self.btnTestKey.clicked.connect(self.test_api_key)
        self.btnTemplateHelp.clicked.connect(self.show_template_help)
        self.leRenameTemplate.textEdited.connect(self._rename_test)
        self.cbxMoveFiles.clicked.connect(self.rename_test)
        self.cbxMoveFiles.clicked.connect(self.dir_test)
        self.cbxRenameStrict.clicked.connect(self.rename_test)
        self.leDirectory.textEdited.connect(self.dir_test)
        self.cbxComplicatedParser.clicked.connect(self.switch_parser)

    def rename_test(self) -> None:
        self._rename_test(self.leRenameTemplate.text())

    def dir_test(self) -> None:
        self.lblDir.setText(
            str(pathlib.Path(self.leDirectory.text().strip()).absolute()) if self.cbxMoveFiles.isChecked() else ""
        )

    def _rename_test(self, template: str) -> None:
        fr = FileRenamer(md_test, platform="universal" if self.cbxRenameStrict.isChecked() else "auto")
        fr.move = self.cbxMoveFiles.isChecked()
        fr.set_template(template)
        fr.set_issue_zero_padding(int(self.leIssueNumPadding.text()))
        fr.set_smart_cleanup(self.cbxSmartCleanup.isChecked())
        try:
            self.lblRenameTest.setText(fr.determine_name(".cbz"))
            self.rename_error = None
        except Exception as e:
            self.rename_error = e
            self.lblRenameTest.setText(str(e))

    def switch_parser(self) -> None:
        complicated = self.cbxComplicatedParser.isChecked()

        self.cbxRemoveC2C.setEnabled(complicated)
        self.cbxRemoveFCBD.setEnabled(complicated)
        self.cbxRemovePublisher.setEnabled(complicated)

    def settings_to_form(self) -> None:
        # Copy values from settings to form
        self.leRarExePath.setText(self.options["general"]["rar_exe_path"])
        self.sbNameMatchIdentifyThresh.setValue(self.options["identifier"]["series_match_identify_thresh"])
        self.sbNameMatchSearchThresh.setValue(self.options["comicvine"]["series_match_search_thresh"])
        self.tePublisherFilter.setPlainText("\n".join(self.options["identifier"]["publisher_filter"]))

        self.cbxCheckForNewVersion.setChecked(self.options["general"]["check_for_new_version"])

        self.cbxComplicatedParser.setChecked(self.options["filename"]["complicated_parser"])
        self.cbxRemoveC2C.setChecked(self.options["filename"]["remove_c2c"])
        self.cbxRemoveFCBD.setChecked(self.options["filename"]["remove_fcbd"])
        self.cbxRemovePublisher.setChecked(self.options["filename"]["remove_publisher"])
        self.switch_parser()

        self.cbxUseSeriesStartAsVolume.setChecked(self.options["comicvine"]["use_series_start_as_volume"])
        self.cbxClearFormBeforePopulating.setChecked(self.options["comicvine"]["clear_form_before_populating_from_cv"])
        self.cbxRemoveHtmlTables.setChecked(self.options["comicvine"]["remove_html_tables"])

        self.cbxUseFilter.setChecked(self.options["comicvine"]["always_use_publisher_filter"])
        self.cbxSortByYear.setChecked(self.options["comicvine"]["sort_series_by_year"])
        self.cbxExactMatches.setChecked(self.options["comicvine"]["exact_series_matches_first"])

        self.leKey.setText(self.options["comicvine"]["cv_api_key"])
        self.leURL.setText(self.options["comicvine"]["cv_url"])

        self.cbxAssumeLoneCreditIsPrimary.setChecked(self.options["cbl"]["assume_lone_credit_is_primary"])
        self.cbxCopyCharactersToTags.setChecked(self.options["cbl"]["copy_characters_to_tags"])
        self.cbxCopyTeamsToTags.setChecked(self.options["cbl"]["copy_teams_to_tags"])
        self.cbxCopyLocationsToTags.setChecked(self.options["cbl"]["copy_locations_to_tags"])
        self.cbxCopyStoryArcsToTags.setChecked(self.options["cbl"]["copy_storyarcs_to_tags"])
        self.cbxCopyNotesToComments.setChecked(self.options["cbl"]["copy_notes_to_comments"])
        self.cbxCopyWebLinkToComments.setChecked(self.options["cbl"]["copy_weblink_to_comments"])
        self.cbxApplyCBLTransformOnCVIMport.setChecked(self.options["cbl"]["apply_cbl_transform_on_cv_import"])
        self.cbxApplyCBLTransformOnBatchOperation.setChecked(
            self.options["cbl"]["apply_cbl_transform_on_bulk_operation"]
        )

        self.leRenameTemplate.setText(self.options["rename"]["template"])
        self.leIssueNumPadding.setText(str(self.options["rename"]["issue_number_padding"]))
        self.cbxSmartCleanup.setChecked(self.options["rename"]["use_smart_string_cleanup"])
        self.cbxChangeExtension.setChecked(self.options["rename"]["set_extension_based_on_archive"])
        self.cbxMoveFiles.setChecked(self.options["rename"]["move_to_dir"])
        self.leDirectory.setText(self.options["rename"]["dir"])
        self.cbxRenameStrict.setChecked(self.options["rename"]["strict"])

    def accept(self) -> None:
        self.rename_test()
        if self.rename_error is not None:
            if isinstance(self.rename_error, ValueError):
                logger.exception("Invalid format string: %s", self.options["rename"]["template"])
                QtWidgets.QMessageBox.critical(
                    self,
                    "Invalid format string!",
                    "Your rename template is invalid!"
                    f"<br/><br/>{self.rename_error}<br/><br/>"
                    "Please consult the template help in the "
                    "settings and the documentation on the format at "
                    "<a href='https://docs.python.org/3/library/string.html#format-string-syntax'>"
                    "https://docs.python.org/3/library/string.html#format-string-syntax</a>",
                )
                return
            else:
                logger.exception(
                    "Formatter failure: %s metadata: %s", self.options["rename"]["template"], self.renamer.metadata
                )
                QtWidgets.QMessageBox.critical(
                    self,
                    "The formatter had an issue!",
                    "The formatter has experienced an unexpected error!"
                    f"<br/><br/>{type(self.rename_error).__name__}: {self.rename_error}<br/><br/>"
                    "Please open an issue at "
                    "<a href='https://github.com/comictagger/comictagger'>"
                    "https://github.com/comictagger/comictagger</a>",
                )

        # Copy values from form to settings and save
        self.options["general"]["rar_exe_path"] = str(self.leRarExePath.text())

        # make sure rar program is now in the path for the rar class
        if self.options["general"]["rar_exe_path"]:
            utils.add_to_path(os.path.dirname(self.options["general"]["rar_exe_path"]))

        if not str(self.leIssueNumPadding.text()).isdigit():
            self.leIssueNumPadding.setText("0")

        self.options["general"]["check_for_new_version"] = self.cbxCheckForNewVersion.isChecked()

        self.options["identifier"]["series_match_identify_thresh"] = self.sbNameMatchIdentifyThresh.value()
        self.options["comicvine"]["series_match_search_thresh"] = self.sbNameMatchSearchThresh.value()
        self.options["identifier"]["publisher_filter"] = [
            x.strip() for x in str(self.tePublisherFilter.toPlainText()).splitlines() if x.strip()
        ]

        self.options["filename"]["complicated_parser"] = self.cbxComplicatedParser.isChecked()
        self.options["filename"]["remove_c2c"] = self.cbxRemoveC2C.isChecked()
        self.options["filename"]["remove_fcbd"] = self.cbxRemoveFCBD.isChecked()
        self.options["filename"]["remove_publisher"] = self.cbxRemovePublisher.isChecked()

        self.options["comicvine"]["use_series_start_as_volume"] = self.cbxUseSeriesStartAsVolume.isChecked()
        self.options["comicvine"][
            "clear_form_before_populating_from_cv"
        ] = self.cbxClearFormBeforePopulating.isChecked()
        self.options["comicvine"]["remove_html_tables"] = self.cbxRemoveHtmlTables.isChecked()

        self.options["comicvine"]["always_use_publisher_filter"] = self.cbxUseFilter.isChecked()
        self.options["comicvine"]["sort_series_by_year"] = self.cbxSortByYear.isChecked()
        self.options["comicvine"]["exact_series_matches_first"] = self.cbxExactMatches.isChecked()

        if self.leKey.text().strip():
            self.options["comicvine"]["cv_api_key"] = self.leKey.text().strip()
            self.talker_api.api_key = self.options["comicvine"]["cv_api_key"]

        if self.leURL.text().strip():
            self.options["comicvine"]["cv_url"] = self.leURL.text().strip()
            self.talker_api.api_url = self.options["comicvine"]["cv_url"]

        self.options["cbl"]["assume_lone_credit_is_primary"] = self.cbxAssumeLoneCreditIsPrimary.isChecked()
        self.options["cbl"]["copy_characters_to_tags"] = self.cbxCopyCharactersToTags.isChecked()
        self.options["cbl"]["copy_teams_to_tags"] = self.cbxCopyTeamsToTags.isChecked()
        self.options["cbl"]["copy_locations_to_tags"] = self.cbxCopyLocationsToTags.isChecked()
        self.options["cbl"]["copy_storyarcs_to_tags"] = self.cbxCopyStoryArcsToTags.isChecked()
        self.options["cbl"]["copy_notes_to_comments"] = self.cbxCopyNotesToComments.isChecked()
        self.options["cbl"]["copy_weblink_to_comments"] = self.cbxCopyWebLinkToComments.isChecked()
        self.options["cbl"]["apply_cbl_transform_on_cv_import"] = self.cbxApplyCBLTransformOnCVIMport.isChecked()
        self.options["cbl"][
            "apply_cbl_transform_on_bulk_operation"
        ] = self.cbxApplyCBLTransformOnBatchOperation.isChecked()

        self.options["rename"]["template"] = str(self.leRenameTemplate.text())
        self.options["rename"]["issue_number_padding"] = int(self.leIssueNumPadding.text())
        self.options["rename"]["use_smart_string_cleanup"] = self.cbxSmartCleanup.isChecked()
        self.options["rename"]["set_extension_based_on_archive"] = self.cbxChangeExtension.isChecked()
        self.options["rename"]["move_to_dir"] = self.cbxMoveFiles.isChecked()
        self.options["rename"]["dir"] = self.leDirectory.text()

        self.options["rename"]["strict"] = self.cbxRenameStrict.isChecked()

        settings.Manager().save_file(self.options, self.options["runtime"]["config"].user_config_dir / "settings.json")
        self.parent().options = self.options
        QtWidgets.QDialog.accept(self)

    def select_rar(self) -> None:
        self.select_file(self.leRarExePath, "RAR")

    def clear_cache(self) -> None:
        ImageFetcher(self.options["runtime"]["config"].cache_folder).clear_cache()
        ComicCacher(self.options["runtime"]["config"].cache_folder, version).clear_cache()
        QtWidgets.QMessageBox.information(self, self.name, "Cache has been cleared.")

    def test_api_key(self) -> None:
        if self.talker_api.check_api_key(self.leKey.text().strip(), self.leURL.text().strip()):
            QtWidgets.QMessageBox.information(self, "API Key Test", "Key is valid!")
        else:
            QtWidgets.QMessageBox.warning(self, "API Key Test", "Key is NOT valid.")

    def reset_settings(self) -> None:
        self.options = settings.Manager(self.options["option_definitions"]).defaults()
        self.settings_to_form()
        QtWidgets.QMessageBox.information(self, self.name, self.name + " have been returned to default values.")

    def select_file(self, control: QtWidgets.QLineEdit, name: str) -> None:

        dialog = QtWidgets.QFileDialog(self)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)

        if platform.system() == "Windows":
            if name == "RAR":
                flt = "Rar Program (Rar.exe)"
            else:
                flt = "Libraries (*.dll)"
            dialog.setNameFilter(flt)
        else:
            dialog.setFilter(QtCore.QDir.Filter.Files)

        dialog.setDirectory(os.path.dirname(str(control.text())))
        if name == "RAR":
            dialog.setWindowTitle("Find " + name + " program")
        else:
            dialog.setWindowTitle("Find " + name + " library")

        if dialog.exec():
            file_list = dialog.selectedFiles()
            control.setText(str(file_list[0]))

    def show_rename_tab(self) -> None:
        self.tabWidget.setCurrentIndex(5)

    def show_template_help(self) -> None:
        template_help_win = TemplateHelpWindow(self)
        template_help_win.setModal(False)
        template_help_win.show()


class TemplateHelpWindow(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)

        uic.loadUi(ui_path / "TemplateHelp.ui", self)
