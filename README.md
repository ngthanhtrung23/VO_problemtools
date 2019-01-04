# Problem tools for VNOI Online contests

## Installation

```
pip install -r requirements.txt
```

## Run problem verification

```
python verify.py <path/to/problem/dir>
```

This will verify that:

- Total score of all subtasks matches problem score,
- All input have matching output (based on filename),
- Input satisfies input_validator,
- Compile and run all solutions,
- Compile and run output checker,
- Check that each solution has score in range $[min\_score, max\_score]$.

## Problem folder structure:

```
problem_dir
|- input_validator/
|- output_checker/
|- submissions/
|- tests/
|- config.yaml
```

## config.yaml

`config.yaml` contains all information about the problem.

Sample file:

```yaml
limits:
        time_secs: 2
        memory_mbs: 1024
problem:
        score: 70
        checker: p1_checker.cpp
        input_validator: validator.cpp
subtasks:
        - regex: sub0.*
          score: 0
          id: 0
        - regex: sub1.*
          score: 11
          id: 1
        - regex: sub2.*
          score: 12
          id: 2
solutions:
        - name: AC_leanhduc_scan.cpp
          min_score: 70
          max_score: 70
        - name: WA_ming.cpp
          min_score: 10
          max_score: 20
```

Notes:

- Checker's full path should be `problem_dir/output_checker/$checker_path$` where `$checker_path$` is configured in `problem.yaml`.
- Input validator's full path should be `problem_dir/input_validator/$input_validator$` where `$input_validator$` is configured in `problem.yaml`.
- All submissions should be inside `problem_dir/submissions`.
- Subtask can have `score = 0`. This is usually used for sample test data.
- `subtask.id` must match what being used in input validator.
