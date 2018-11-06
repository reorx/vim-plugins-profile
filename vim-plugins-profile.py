#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# vim-profiler - Utility script to profile (n)vim (e.g. startup)
# Copyright © 2015 Benjamin Chrétien
# Copyright © 2017-2018 Hörmet Yiltiz <hyiltiz@github.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function

import os
import sys
import subprocess
import re
import csv
import operator
import argparse
import collections


def to_list(cmd):
    if not isinstance(cmd, (list, tuple)):
        cmd = cmd.split(' ')
    return cmd


def get_exe(cmd):
    # FIXME: this assumes that the first word is the executable
    return to_list(cmd)[0]


def is_subdir(paths, subdir):
    # See: http://stackoverflow.com/a/18115684/1043187
    for path in paths:
        path = os.path.realpath(path)
        subdir = os.path.realpath(subdir)
        reldir = os.path.relpath(subdir, path)
        if not (reldir == os.pardir or reldir.startswith(os.pardir + os.sep)):
            return True
    return False


class StartupData(object):
    """
    Data for (n)vim startup (timings etc.).
    """

    def __init__(self, cmd, log_filename, check_system=False):
        super(StartupData, self).__init__()
        self.cmd = cmd
        self.log_filename = log_filename
        self.log_txt = None
        self.times = dict()
        self.system_dirs = ["/usr", "/usr/local"]
        self.generate(check_system)

    def generate(self, check_system=False):
        """
        Generate startup data.
        """
        self._run_vim()
        try:
            self._load_times(check_system)
        except RuntimeError:
            print("\nNo plugin found. Exiting.")
            sys.exit()

        if not self.times:
            sys.exit()

    def _guess_plugin_dir(self, log_txt):
        """
        Try to guess the vim directory containing plugins.
        """
        candidates = list()

        # Get common plugin dir if any
        vim_subdirs = "autoload|ftdetect|plugin|syntax"
        matches = re.findall(
            "^\d+.\d+\s+\d+.\d+\s+\d+.\d+: "
            "sourcing (.+?)/(?:[^/]+/)(?:%s)/[^/]+" % vim_subdirs,
            log_txt,
            re.MULTILINE,
        )
        for plugin_dir in matches:
            # Ignore system plugins
            if not is_subdir(self.system_dirs, plugin_dir):
                candidates.append(plugin_dir)

        if candidates:
            # FIXME: the directory containing vimrc could be returned as well
            return collections.Counter(candidates).most_common(1)[0][0]
        else:
            raise RuntimeError("no user plugin found")

    def _load_times(self, check_system=False):
        """
        Load startup times for log file.
        """
        # Load log file and process it
        print("Loading and processing logs...", end="")
        with open(self.log_filename, 'r') as log:
            log_txt = log.read()
            self.log_txt = log_txt
            plugin_dir = ""

            # Try to guess the folder based on the logs themselves
            try:
                plugin_dir = self._guess_plugin_dir(log_txt)
                matches = re.findall(
                    "^\d+.\d+\s+\d+.\d+\s+(\d+.\d+): "
                    "sourcing %s/([^/]+)/" % plugin_dir,
                    log_txt,
                    re.MULTILINE,
                )
                for res in matches:
                    time = res[0]
                    plugin = res[1]
                    if plugin in self.times:
                        self.times[plugin] += float(time)
                    else:
                        self.times[plugin] = float(time)
            # Catch exception if no plugin was found
            except RuntimeError as e:
                if not check_system:
                    raise
                else:
                    plugin_dir = ""

            if check_system:
                for d in self.system_dirs:
                    matches = re.findall(
                        "^\d+.\d+\s+\d+.\d+\s+(\d+.\d+): "
                        "sourcing %s/.+/([^/]+.vim)\n" % d,
                        log_txt,
                        re.MULTILINE,
                    )
                    for res in matches:
                        time = res[0]
                        plugin = "*%s" % res[1]
                        if plugin in self.times:
                            self.times[plugin] += float(time)
                        else:
                            self.times[plugin] = float(time)

        print(" done.")
        if plugin_dir:
            print("Plugin directory: %s" % plugin_dir)
        else:
            print("No user plugin found.")
        if not self.times:
            print("No system plugin found.")

    def _run_vim(self):
        """
        Run vim/nvim to generate startup logs.
        """
        print("Running %s to generate startup logs..." % get_exe(self.cmd))
        self._clean_log()
        full_cmd = to_list(self.cmd) + [
            "--startuptime",
            self.log_filename,
            "-f",
            "-c",
            "q",
        ]
        print('cmd: {}'.format(' '.join(full_cmd)))
        subprocess.call(full_cmd, shell=False)

    def _clean_log(self):
        """
        Clean log file.
        """
        if os.path.isfile(self.log_filename):
            os.remove(self.log_filename)

    def __del__(self):
        """
        Destructor taking care of clean up.
        """
        self._clean_log()


class StartupAnalyzer(object):
    """
    Analyze startup times for (n)vim.
    """

    def __init__(self, param, debug=False):
        super(StartupAnalyzer, self).__init__()
        self.runs = param.runs
        self.cmd = param.cmd
        self.raw_data = [
            StartupData(
                self.cmd, "vim_%i.log" % (i + 1), check_system=param.check_system
            )
            for i in range(self.runs)
        ]
        self.data = self.process_data()
        self.debug = debug

        if self.debug:
            for i in self.raw_data:
                print('log file: {}, content:\n{}'.format(i.log_filename, i.log_txt))

    def process_data(self):
        """
        Merge startup times for each plugin.
        """
        return {
            k: [d.times[k] for d in self.raw_data]
            for k in self.raw_data[0].times.keys()
        }

    def average_data(self):
        """
        Return average times for each plugin.
        """
        return {k: sum(v) / len(v) for k, v in self.data.items()}

    def export(self, output_filename="result.csv"):
        """
        Write sorted result to file.
        """
        assert len(self.data) > 0
        print("Writing result to %s..." % output_filename, end="")
        with open(output_filename, 'w') as fp:
            writer = csv.writer(fp)
            # Compute average times
            avg_data = self.average_data()
            # Sort by average time
            for name, avg_time in sort_data(avg_data):
                writer.writerow(["%.3f" % avg_time, name])
        print(" done.")

    def print_summary(self, n):
        """
        Print summary of startup times for plugins.
        """
        lines = []

        # Compute average times
        avg_data = self.average_data()
        # Sort by average time
        rank = 0
        sorted_data = sort_data(avg_data)
        if n != 0:
            sorted_data = sorted_data[:n]
        for name, time in sorted_data:
            rank += 1
            lines.append("{:>3}   {:7.3f}   {}".format(rank, time, name))

        # prints
        max_width = max([len(i) for i in lines])
        buf = []
        buf.append("Plugin startup times:")
        # head
        head_sep = "{:->3}   {:->7}   {}".format('', '', '-' * (max_width - 16))
        buf.append(head_sep)
        buf.append("{:>3}   {:>7}   {}".format('#', 'ms', 'plugin'))
        buf.append(head_sep)
        # body
        buf.extend(lines)

        print('\n'.join(buf))


def sort_data(d, reverse=True):
    """
    Sort data by decreasing time.
    """
    return sorted(d.items(), key=operator.itemgetter(1), reverse=reverse)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze startup times of vim/neovim plugins.'
    )
    parser.add_argument("-o", dest="csv", type=str, help="Export result to a csv file")
    parser.add_argument(
        "-s",
        dest="check_system",
        action='store_true',
        help="Consider system plugins as well (marked with *)",
    )
    parser.add_argument(
        "-n",
        dest="n",
        type=int,
        default=0,
        help="Number of plugins to list in the summary",
    )
    parser.add_argument(
        "-r",
        dest="runs",
        type=int,
        default=1,
        help="Number of runs (for average/standard deviation)",
    )
    parser.add_argument(
        dest="cmd",
        nargs=argparse.REMAINDER,
        type=str,
        default="nvim",
        help="vim/neovim executable or command",
    )
    parser.add_argument('-d', '--debug', action='store_true', help='enable debug log')

    # Parse CLI arguments
    args = parser.parse_args()
    output_filename = args.csv
    n = args.n

    # Command (default = vim)
    if args.cmd == []:
        args.cmd = "nvim"

    # Run analysis
    analyzer = StartupAnalyzer(args, debug=args.debug)
    analyzer.print_summary(n)
    if output_filename is not None:
        analyzer.export(output_filename)


if __name__ == "__main__":
    main()
