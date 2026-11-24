"""Temporary: proves a red shard fails the gate (#207). Removed in the next commit."""


def test_a_deliberately_failing_test_in_one_shard():
    assert False, "deliberate failure for #207"
