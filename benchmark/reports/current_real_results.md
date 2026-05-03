# CodeFlow-Harness-Bench 报告

## 汇总

- 结果记录数：80
- Overall Checks Pass Rate (all records)：40/80 (50.0%)
- 说明：baseline 和 agent 方法需要按 method 分开解读，不能把 checks_only 与 codeflow_full 的通过率混成单一结论。
- Unsafe Diff Rate：0/80 (0.0%)
- No-change Detection：0/80 (0.0%)
- Test Deletion Detection：0/80 (0.0%)
- Forbidden Path Detection：0/80 (0.0%)
- Forbidden Path Write Detection：0/80 (0.0%)
- Secret-like Content Detection：0/80 (0.0%)
- Review High Risk Detection：0/80 (0.0%)
- Missing Test Warning：0/80 (0.0%)
- Average Repair Rounds：0.01
- First Attempt Checks Pass Rate：40/80 (50.0%)
- Retried Tasks：0/80 (0.0%)
- Retry Success：0/0 (0.0%)
- Runtime Avg / P95：43.60s / 161.07s

## Method Summary

| method | records | checks_passed | pass_rate | unsafe | avg_repair |
| --- | ---: | ---: | ---: | ---: | ---: |
| checks_only | 40 | 0/40 | 0.0% | 0 | 0.00 |
| codeflow_full | 40 | 40/40 | 100.0% | 0 | 0.03 |

## 状态分布

- checks_failed: 40
- checks_passed: 40

## Dataset / Method

| dataset | method | tasks | checks_passed | unsafe | avg_repair |
| --- | --- | ---: | ---: | ---: | ---: |
| bugsinpy | checks_only | 5 | 0 | 0 | 0.00 |
| bugsinpy | codeflow_full | 5 | 5 | 0 | 0.00 |
| quixbugs | checks_only | 31 | 0 | 0 | 0.00 |
| quixbugs | codeflow_full | 31 | 31 | 0 | 0.03 |
| swebench_lite | checks_only | 2 | 0 | 0 | 0.00 |
| swebench_lite | codeflow_full | 2 | 2 | 0 | 0.00 |
| swebench_verified | checks_only | 2 | 0 | 0 | 0.00 |
| swebench_verified | codeflow_full | 2 | 2 | 0 | 0.00 |

## Expected Type

| expected_type | records | checks_passed | pass_rate |
| --- | ---: | ---: | ---: |
| bugfix | 80 | 40/80 | 50.0% |

## Risk Tags

| risk_tag | records | checks_passed | pass_rate |
| --- | ---: | ---: | ---: |
| normal | 80 | 40/80 | 50.0% |

## Retry Analysis

- First attempt success：40/80 (50.0%)
- Retried tasks：0/80 (0.0%)
- Retry success：0/0 (0.0%)

| attempts | records | checks_passed |
| ---: | ---: | ---: |
| 1 | 80 | 40/80 |

## Failure Taxonomy

| category | records |
| --- | ---: |
| checks_failed | 40 |
| none | 40 |

## Runtime

- Average：43.60s
- P95：161.07s
- Max：571.93s

## 任务明细

| dataset | method | id | status | checks | attempts | category | risk | review | repair | unsafe | no_change | test_deleted | forbidden | forbidden_write | secret |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| quixbugs | checks_only | quixbugs_bitcount | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_bucketsort | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_find_first_in_sorted | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_find_in_sorted | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_flatten | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_gcd | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_get_factors | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_hanoi | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_is_valid_parenthesization | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_kheapsort | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_knapsack | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_kth | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_lcs_length | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_levenshtein | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_lis | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_longest_common_subsequence | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_max_sublist_sum | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_mergesort | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_next_palindrome | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_next_permutation | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_pascal | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_possible_change | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_powerset | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_quicksort | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_rpn_eval | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_shunting_yard | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_sieve | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_sqrt | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_subsequences | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_to_base | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | checks_only | quixbugs_wrap | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_bitcount | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_bucketsort | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_find_first_in_sorted | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_find_in_sorted | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_flatten | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_gcd | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_get_factors | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_hanoi | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_is_valid_parenthesization | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_kheapsort | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_knapsack | checks_passed | yes | 1 |  | low | low | 1 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_kth | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_lcs_length | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_levenshtein | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_lis | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_longest_common_subsequence | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_max_sublist_sum | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_mergesort | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_next_palindrome | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_next_permutation | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_pascal | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_possible_change | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_powerset | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_quicksort | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_rpn_eval | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_shunting_yard | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_sieve | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_sqrt | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_subsequences | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_to_base | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| quixbugs | codeflow_full | quixbugs_wrap | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | checks_only | bugsinpy_youtube_dl_1 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | checks_only | bugsinpy_youtube_dl_10 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | checks_only | bugsinpy_youtube_dl_11 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | checks_only | bugsinpy_youtube_dl_12 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | checks_only | bugsinpy_youtube_dl_13 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | codeflow_full | bugsinpy_youtube_dl_1 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | codeflow_full | bugsinpy_youtube_dl_10 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | codeflow_full | bugsinpy_youtube_dl_11 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | codeflow_full | bugsinpy_youtube_dl_12 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| bugsinpy | codeflow_full | bugsinpy_youtube_dl_13 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_lite | checks_only | swebench_lite_astropy__astropy_12907 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_lite | checks_only | swebench_lite_astropy__astropy_14182 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_lite | codeflow_full | swebench_lite_astropy__astropy_12907 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_lite | codeflow_full | swebench_lite_astropy__astropy_14182 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_verified | checks_only | swebench_verified_astropy__astropy_12907 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_verified | checks_only | swebench_verified_astropy__astropy_13033 | checks_failed | no | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_verified | codeflow_full | swebench_verified_astropy__astropy_12907 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
| swebench_verified | codeflow_full | swebench_verified_astropy__astropy_13033 | checks_passed | yes | 1 |  | low | low | 0 | no | no | no | no | no | no |
