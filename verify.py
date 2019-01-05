# -*- coding: UTF-8 -*-

import datetime
import re
import resource
import subprocess
import sys
import yaml

from argparse import ArgumentParser
from enum import Enum
from pathlib import Path
from termcolor import colored

COMPILE_COMMAND = "g++-8 %(code_path)s " \
                  "--std=c++14 -O2 " \
                  "-I testlib/ " \
                  "-o %(exec_path)s"

# EPS for comparing scores.
EPS = 10 ** -6

# Input and output file format
INPUT_SUFFIX = ".inp"
OUTPUT_SUFFIX = ".out"

# Clear last line in terminal
CURSOR_UP_ONE = '\x1b[1A'
ERASE_LINE = '\x1b[2K'


def erase_terminal_line():
    sys.stdout.write(CURSOR_UP_ONE)
    sys.stdout.write(ERASE_LINE)


# For printing verification status
TICK = '✔'
CROSS = '✘'


def verification_status(message: str, success: bool):
    sign = TICK if success else CROSS
    color = 'green' if success else 'red'
    print("[" + colored(sign, color) + "] " + message)


def verification_success(message: str):
    verification_status(message, True)


def verification_failed(message: str):
    verification_status(message, False)


class Verdict(Enum):
    UNKNOWN = 0
    AC = 1
    WA = 2
    TL = 3
    RE = 4

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class TestVerdict:
    """
    TestVerdict contains verdict for a single test case, which includes:
    - verdict: AC / WA / TL / RE / ...
    - exec_time: running time of solution in second.
    """

    def __init__(self, verdict: Verdict, exec_time: float, input_name: str):
        self.verdict = verdict
        self.exec_time = exec_time
        self.input_path = input_name

    def __str__(self):
        if self.verdict == Verdict.TL:
            return str(self.verdict) + " -----"
        else:
            return str(self.verdict) + " " + "{:.2f}".format(self.exec_time) + "s"


class SubtaskVerdict:
    """
    SubtaskVerdict contains verdict for a single subtask, which includes:
    - score: total score solution receives for this subtask.
    - test_verdicts: list of TestVerdict.
    """

    def __init__(self, subtask_id: int):
        self.test_verdicts = []
        self.score = 0
        self.subtask_id = subtask_id

    def add_test_verdict(self, test_verdict: TestVerdict):
        self.test_verdicts.append(test_verdict)

    def set_score(self, score: float):
        self.score = score

    def __str__(self):
        rejected_verdicts = [t.verdict for t in self.test_verdicts if t.verdict != Verdict.AC]
        combined_verdict = str(set(rejected_verdicts)) if rejected_verdicts else 'AC'
        times = sorted([t.exec_time for t in self.test_verdicts if t.exec_time >= 0])

        if len(times) <= 8:
            times_str = ["{:.2f}".format(time) for time in times]
        else:
            times_str = ["{:.2f}".format(time) for time in times[:4]] + ["..."] + ["{:.2f}".format(time) for time in
                                                                                   times[-4:]]
        return combined_verdict + ", score = {:.2f}".format(self.score) + ", times = " + str(times_str)


class ProblemVerdict:
    """
    ProblemVerdict is a verdict of a submission for a problem, which includes:
    - total_score.
    - verdicts: list of SubtaskVerdict.
    """

    def __init__(self):
        self.verdicts = []
        self.total_score = 0.0

    def add_subtask_verdict(self, verdict: SubtaskVerdict):
        self.verdicts.append(verdict)
        self.total_score += verdict.score


class Test:
    def __init__(self, tests_path: Path, input: str, output: str, subtask_id: int):
        self.input_path = tests_path / input
        self.output_path = tests_path / output
        self.subtask_id = subtask_id


class Subtask:
    def __init__(self, tests_path: Path, regex: str, score: int, subtask_id: int):
        self.score = score
        self.regex = regex
        self.subtask_id = subtask_id

        self.tests = []
        compiled_regex = re.compile(regex)
        for filename in tests_path.iterdir():
            if compiled_regex.match(filename.name) and filename.suffix == INPUT_SUFFIX:
                test_name = filename.name[:filename.name.find('.')]
                test = Test(tests_path,
                            input=test_name + INPUT_SUFFIX,
                            output=test_name + OUTPUT_SUFFIX,
                            subtask_id=subtask_id)
                self.tests.append(test)

    def __str__(self):
        return "id: %d; score: %d; %d tests" % (self.subtask_id, self.score, len(self.tests))


class Problem:
    def __init__(self, relative_path):
        # self.path = Path to problem directory.
        try:
            self.path = Path(relative_path)
        except FileNotFoundError:
            raise ValueError("Problem dir does not exist: '%s'", relative_path)
        verification_success("Problem dir found at %s" % self.path.resolve())

        # self.config_path = Path to config file.
        self.config_path = self.path / "config.yaml"
        with open(self.config_path.absolute(), 'r') as stream:
            try:
                self.config = yaml.load(stream)
            except yaml.YAMLError as err:
                raise ValueError("Could not load config file %s", str(err))

        # self.tests_path = Path to test directory.
        self.tests_path = self.path / "tests"
        if not self.tests_path.is_dir():
            raise ValueError("Test directory not found. Please rename test dir to 'tests'")

        # self.subtasks
        self.subtasks = []
        for subtask in self.config['subtasks']:
            sub = Subtask(self.tests_path, subtask['regex'], subtask['score'], int(subtask['id']))
            self.subtasks.append(sub)
        verification_success(
            "%d subtasks, scores = %s" % (len(self.subtasks), [subtask.score for subtask in self.subtasks]))

        # self.submission_path = Path to submission directory.
        self.submission_path = self.path / "submissions"
        if not self.submission_path.is_dir():
            raise ValueError("Submission dir not found. Please name it 'submissions'")
        verification_success("Submission dir found.")

        # Input validator
        if 'input_validator' not in self.config['problem']:
            raise ValueError("input_validator not configured")

        self.input_validator_path = self.path / "input_validator" / self.config['problem']['input_validator']
        if not self.input_validator_path.exists():
            raise ValueError("Input validator not found %s" % self.input_validator_path.resolve())

        self.input_validator_exec_path = Path("./tmp") / "input_validator"
        compile_cpp(self.input_validator_path, self.input_validator_exec_path)
        verification_success("Input validator found at %s" % self.input_validator_path.resolve())

        # self.verifier
        if 'checker' in self.config['problem']:
            self.verifier_path = self.path / "output_checker" / self.config['problem']['checker']
            if not self.verifier_path.exists():
                raise ValueError("Output checker not found: %s" % self.verifier_path.resolve())

            self.verifier_exec_path = Path("./tmp") / "checker"
            compile_cpp(self.verifier_path, self.verifier_exec_path)
            verification_success("Found and compiled checker %s" % self.config['problem']['checker'])
        else:
            self.verifier_path = None
            self.verifier_exec_path = None
            verification_success("No checker required. Using default checker `diff -w`")

    def verify_tests(self):
        """
        Make sure all tests have input + output.
        """

        # Verify that number of input file == number of output file.
        cnt_input = count_file_with_extension(self.tests_path, "inp")
        cnt_output = count_file_with_extension(self.tests_path, "out")
        if cnt_input != cnt_output:
            verification_failed("ERROR: Number of input and output files NOT match: Found %s input and %s output" % (
                cnt_input, cnt_output))

        verification_success("Found %s tests" % cnt_input)

        # Verify that the set of file names of all inputs matches the set of file names of all outputs.
        input_file_names = set(
            [filename.with_suffix('').name for filename in self.tests_path.iterdir() if
             filename.suffix == INPUT_SUFFIX])
        output_file_names = set(
            [filename.with_suffix('').name for filename in self.tests_path.iterdir() if
             filename.suffix == OUTPUT_SUFFIX])
        if input_file_names == output_file_names:
            verification_success("Input and output file names match")
        else:
            verification_failed("Input and output file names not match:\nIn - Out = %s\nOut - In = %s" % (
                input_file_names.difference(output_file_names), output_file_names.difference(input_file_names)))

    def verify_subtasks(self):
        # Verify total score of all subtask == problem score.
        total_score = sum(subtask.score for subtask in self.subtasks)
        if total_score != int(self.config['problem']['score']):
            verification_failed("Total score of all subtask = %d, NOT matching problem config's total score = %d"
                                % (total_score, self.config['problem']['score']))

        # Verify each subtask has at least 1 test.
        for subtask in self.subtasks:
            if len(subtask.tests) == 0:
                verification_failed("Subtask %d has 0 tests" % subtask.subtask_id)
            else:
                verification_success("Subtask %d has %d tests" % (subtask.subtask_id, len(subtask.tests)))

            input_validator_passed = True
            for test in subtask.tests:
                filename = str(test.input_path.resolve())

                # We convert all \r\n to \n and update the original input file.
                content = open(filename, 'r').read()
                with open(filename, 'w', newline="\n") as f:
                    f.write(content)

                # Run input validator on input file.
                inp = open(filename)
                command = [self.input_validator_exec_path.resolve(),
                           str(subtask.subtask_id),
                           test.input_path.resolve()]
                output = None
                try:
                    output = subprocess.run(command,
                                            stdin=inp,
                                            stderr=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE,
                                            shell=False)
                except subprocess.CalledProcessError as err:
                    verification_failed("Test %s failed input_validator: %s" % (test.input_path.resolve(), str(err)))
                    input_validator_passed = False
                    if output is not None:
                        print(output)

            if input_validator_passed:
                verification_success("Subtask %d passed input validator." % subtask.subtask_id)

    def verify_submissions(self):
        """
        Verify all problems received score in range [min_score, max_score].
        """

        if 'solutions' not in self.config:
            verification_failed("No solutions found")
            return

        log_name = "./logs/" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        with open(log_name, 'w') as log_stream:
            for submission in self.config['solutions']:
                filename = str(submission['name'])
                print("Running %s" % filename)
                code_path = self.submission_path / filename
                exec_path = Path("./tmp") / filename[:filename.find('.')]

                compile_cpp(code_path, exec_path)
                problem_verdict = self.judge_exec(exec_path)
                score = problem_verdict.total_score

                min_score = submission['min_score']
                max_score = submission['max_score']

                if score < min_score - EPS:
                    verification_failed("%s received %.1f, min_score = %.1f" % (filename, score, min_score))
                elif score > max_score + EPS:
                    verification_failed("%s received %.1f, max_score = %.1f" % (filename, score, max_score))
                else:
                    verification_success(
                        "%s received %.1f, in range [%.1f, %.1f]" % (filename, score, min_score, max_score))

                log_stream.write("Judge verdict for " + filename + "\n")
                for subtask_verdict in problem_verdict.verdicts:
                    log_stream.write("- Subtask " + str(subtask_verdict.subtask_id) + "\n")
                    for test_verdict in subtask_verdict.test_verdicts:
                        log_stream.write("    " + str(test_verdict) + " " + test_verdict.input_path + "\n")

        verification_success("Printed judge log to %s" % log_name)

    def judge_exec(self, exec_path: Path) -> ProblemVerdict:
        """
        Judge an executable, and return the score.
        """

        time_limit_secs = int(self.config['limits']['time_secs'])
        problem_verdict = ProblemVerdict()

        for subtask in self.subtasks:
            print("- Running Subtask %d" % subtask.subtask_id)

            if len(subtask.tests) == 0:
                # Note that this is already checked in verify_subtasks, so we just skip and do not print anything here.
                continue

            correct_tests = 0

            subtask_verdict = SubtaskVerdict(subtask.subtask_id)
            for test in subtask.tests:
                output_path = Path("./tmp") / "out"
                test_verdict = run_code(exec_path, test.input_path, output_path, time_limit_secs)

                if test_verdict.verdict == Verdict.UNKNOWN:
                    # WA or AC?
                    if self.verify_output(test, output_path):
                        correct_tests += 1
                        test_verdict.verdict = Verdict.AC
                    else:
                        test_verdict.verdict = Verdict.WA

                subtask_verdict.add_test_verdict(test_verdict)

            subtask_verdict.set_score(correct_tests * 1.0 / len(subtask.tests) * subtask.score)

            erase_terminal_line()
            print("- Subtask %d, verdict = %s" % (subtask.subtask_id, subtask_verdict))
            problem_verdict.add_subtask_verdict(subtask_verdict)

        return problem_verdict

    def verify_output(self, test: Test, output_path: Path) -> bool:
        """
        Verify output of a submission.

        - If output verifier is present, use it,
        - Otherwise, `diff` is used.
        """

        if self.verifier_exec_path is None:
            command = ['diff',
                       '-w',
                       test.output_path.resolve(),
                       output_path.resolve()]
        else:
            command = [self.verifier_exec_path.resolve(),
                       test.input_path.resolve(),
                       output_path.resolve(),
                       test.output_path.resolve()]

        try:
            subprocess.check_call(command, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError as err:
            return False


def count_file_with_extension(path: Path, extension: str) -> int:
    cnt = 0
    for filename in path.iterdir():
        if not filename.is_dir() and filename.suffix == "." + extension:
            cnt += 1
    return cnt


def compile_cpp(code_path: Path, exec_path: Path):
    command = COMPILE_COMMAND % {'code_path': code_path.resolve(), 'exec_path': exec_path.resolve()}
    output = None
    try:
        output = subprocess.run(command, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        verification_failed("ERROR: Compile error for %s" % code_path.resolve())
        print(e)

        if output is not None:
            print("------")
            print("Compile output:")
            print(output)


def get_children_process_elapsed_time() -> float:
    """
    :return: How much time children processes used.
    """
    info = resource.getrusage(resource.RUSAGE_CHILDREN)
    return info.ru_utime + info.ru_stime


def run_code(exec_path: Path, input_path: Path, output_path: Path, time_limit_secs: int) -> TestVerdict:
    """
    Run code, given time limit.

    Returns True if code successfully finish execution, False otherwise.
    """
    input_name = input_path.resolve().name

    # Find total time that children processes use previously.
    elapsed_time = get_children_process_elapsed_time()

    output = None
    try:
        inp = open(str(input_path.resolve()))
        output = subprocess.run(str(exec_path.resolve()),
                                stdin=inp,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                shell=False,
                                timeout=time_limit_secs)
        with open(str(output_path.resolve()), 'wb') as stream:
            stream.write(output.stdout)

        # Execution completed. Either AC or WA.
        return TestVerdict(Verdict.UNKNOWN, get_children_process_elapsed_time() - elapsed_time, input_name)
    except subprocess.CalledProcessError as e:
        print(e)
        if output is not None:
            print("------")
            print("Output:")
            print(output)
        return TestVerdict(Verdict.RE, get_children_process_elapsed_time() - elapsed_time, input_name)
    except subprocess.TimeoutExpired as e:
        return TestVerdict(Verdict.TL, -1, input_name)


def main():
    # Parsing arguments.
    parser = ArgumentParser(description="Verify problem package for VO")
    parser.add_argument('dir')
    args = parser.parse_args()

    try:
        problem = Problem(args.dir)
    except ValueError as e:
        verification_failed("ERROR: %s" % str(e))
        return

    problem.verify_tests()
    problem.verify_subtasks()
    problem.verify_submissions()


if __name__ == '__main__':
    main()
