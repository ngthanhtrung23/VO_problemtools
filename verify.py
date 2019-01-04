import re
import subprocess
import sys
import yaml

from argparse import ArgumentParser
from pathlib import Path

COMPILE_COMMAND = "g++-8 %(code_path)s " \
                  "--std=c++14 -O2 " \
                  "-I testlib/ " \
                  "-o %(exec_path)s"

EPS = 10 ** -6

# Clear last line in terminal
CURSOR_UP_ONE = '\x1b[1A'
ERASE_LINE = '\x1b[2K'


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
            if compiled_regex.match(filename.name) and filename.suffix == ".inp":
                test_name = filename.name[:filename.name.find('.')]
                test = Test(tests_path, input=test_name + ".inp", output=test_name + ".out", subtask_id=subtask_id)
                self.tests.append(test)

    def __str__(self):
        return "id: %d; score: %d; %d tests" % (self.subtask_id, self.score, len(self.tests))


class Problem:
    def __init__(self, relative_path):
        # self.path = Path to problem directory.
        try:
            self.path = Path(relative_path)
        except FileNotFoundError:
            raise ValueError("Problem path does not exist: '%s'", relative_path)
        print("Verify problem at '%s'" % self.path.resolve())

        # self.tests_path = Path to test directory.
        self.tests_path = self.path / "tests"
        if not self.tests_path.is_dir():
            raise ValueError("Test directory not found. Please rename test dir to 'tests'")

        # self.config_path = Path to config file.
        self.config_path = self.path / "config.yaml"
        with open(self.config_path.absolute(), 'r') as stream:
            try:
                self.config = yaml.load(stream)
            except yaml.YAMLError as err:
                raise ValueError("Could not load config file %s", str(err))

        # self.submission_path = Path to submission directory.
        self.submission_path = self.path / "submissions"
        if not self.submission_path.is_dir():
            raise ValueError("Submission directory not found. Please name it 'submissions'")

        # self.subtasks
        self.verify_tests()
        print('Subtasks:')
        self.subtasks = []
        for subtask in self.config['subtasks']:
            sub = Subtask(self.tests_path, subtask['regex'], subtask['score'], int(subtask['id']))
            print("- ", sub)
            self.subtasks.append(sub)

        # self.verifier
        if 'checker' in self.config['problem']:
            self.verifier_path = self.path / "output_checker" / self.config['problem']['checker']
            if not self.verifier_path.exists():
                raise ValueError("Output checker not found: %s" % self.config['problem']['checker'])

            print("Compiling checker..")
            self.verifier_exec_path = Path("./tmp") / "checker"
            compile_cpp(self.verifier_path, self.verifier_exec_path)
        else:
            self.verifier_path = None
            self.verifier_exec_path = None

    def verify_tests(self):
        """
        Make sure all tests have input + output.
        """

        cnt_input = count_file_with_extension(self.tests_path, "inp")
        cnt_output = count_file_with_extension(self.tests_path, "out")
        if cnt_input != cnt_output:
            print("ERROR: Number of input and output files NOT match: Found %s input and %s output", cnt_input,
                  cnt_output)

        print("Found %s tests" % cnt_input)
        # TODO: check for each input, output exists.

    def verify_subtask_scores(self):
        total_score = sum(subtask.score for subtask in self.subtasks)
        if total_score != int(self.config['problem']['score']):
            print("ERROR: Total score of all subtask = %d, does not match problem config's total score = %d"
                  % (total_score, self.config['problem']['score']))

    def verify_submissions(self):
        """
        Verify all problems received score in range [min_score, max_score].
        """

        if 'solutions' not in self.config:
            print("ERROR: No solutions found")
            return

        for submission in self.config['solutions']:
            filename = str(submission['name'])
            print("Judging %s" % filename)
            code_path = self.submission_path / filename
            exec_path = Path("./tmp") / filename[:filename.find('.')]

            compile_cpp(code_path, exec_path)
            score = self.judge_exec(exec_path)

            min_score = submission['min_score']
            max_score = submission['max_score']

            if score < min_score - EPS:
                print("ERROR: %s received %f, min_score = %f" % (filename, score, min_score))

            if score > max_score + EPS:
                print("ERROR: %s received %f, max_score = %f" % (filename, score, max_score))

    def judge_exec(self, exec_path: Path) -> float:
        """
        Judge an executable, and return the score.
        """

        score = 0.0
        time_limit_secs = int(self.config['limits']['time_secs'])
        for subtask in self.subtasks:
            print("- Subtask: ", subtask.regex)

            if len(subtask.tests) == 0:
                print("WARNING: Subtask has 0 tests")
                continue

            print("  Running on tests..")

            score_per_test = 1.0 / len(subtask.tests) * subtask.score
            subtask_score = 0.0
            for test in subtask.tests:
                erase_terminal_line()
                output_path = Path("./tmp") / "out"
                print("  Running on test ", test.input_path)
                if not run_code(exec_path, test.input_path, output_path, time_limit_secs):
                    # RE or TLE
                    continue

                if self.verify_output(test, output_path):
                    subtask_score += score_per_test

            erase_terminal_line()
            print("  Subtask score = %f" % subtask_score)
            score += subtask_score

        print("%s has total score = %f" % (exec_path.name, score))
        return score

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
        print("ERROR: Compile error for %s" % code_path.resolve())
        print(e)

        if output is not None:
            print("------")
            print("Compile output:")
            print(output)


def run_code(exec_path: Path, input_path: Path, output_path: Path, time_limit_secs: int) -> bool:
    """
    Run code, given time limit.

    Returns True if code successfully finish execution, False otherwise.
    """

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
        return True
    except subprocess.CalledProcessError as e:
        print("ERROR: Compile error for %s" % exec_path.resolve())
        print(e)
        if output is not None:
            print("------")
            print("Output:")
            print(output)
        return False
    except subprocess.TimeoutExpired as e:
        return False


def erase_terminal_line():
    sys.stdout.write(CURSOR_UP_ONE)
    sys.stdout.write(ERASE_LINE)


def main():
    # Parsing arguments.
    parser = ArgumentParser(description="Verify problem package for VO")
    parser.add_argument('dir')
    args = parser.parse_args()

    try:
        problem = Problem(args.dir)
    except ValueError as e:
        print("ERROR: %s" % str(e))
        return

    problem.verify_subtask_scores()
    problem.verify_submissions()


if __name__ == '__main__':
    main()
