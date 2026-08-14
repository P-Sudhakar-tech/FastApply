from turboply import dummy_add


def test_dummy_add():
    assert dummy_add(2, 3) == 5


def test_dummy_add_negative():
    assert dummy_add(-1, 1) == 0
