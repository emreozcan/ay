from _pytest.python_api import raises

from mehtap.control_structures import LuaError
from mehtap.values import LuaNumber, LuaNil
from mehtap.vm import VirtualMachine


def execute(program):
    vm = VirtualMachine()
    return vm.exec(program)


def test_no_base():
    assert execute("return tonumber(1)") == [LuaNumber(1)]
    assert execute("return tonumber(2.5)") == [LuaNumber(2.5)]
    assert execute('return tonumber("7.25")') == [LuaNumber(7.25)]
    assert execute('return tonumber("+8.5")') == [LuaNumber(8.5)]
    assert execute('return tonumber("-9.5")') == [LuaNumber(-9.5)]


def test_base():
    with raises(LuaError):
        assert execute("return tonumber(1, 10)") == [LuaNumber(1)]
    with raises(LuaError):
        assert execute("return tonumber(25, 10)") == [LuaNumber(25)]
    assert execute('return tonumber("725", 10)') == [LuaNumber(725)]
    assert execute('return tonumber("+85", 10)') == [LuaNumber(85)]
    assert execute('return tonumber("-95", 10)') == [LuaNumber(-95)]

    assert execute('return tonumber("1", 16)') == [LuaNumber(1)]
    assert execute('return tonumber("19", 16)') == [LuaNumber(25)]
    assert execute('return tonumber("2D5", 16)') == [LuaNumber(725)]
    assert execute('return tonumber("+55", 16)') == [LuaNumber(85)]
    assert execute('return tonumber("-5F", 16)') == [LuaNumber(-95)]

    assert execute(
        'return tonumber("ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ'
        'ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", 36)',
    ) == [LuaNumber(-1)]


def test_fail():
    assert execute(
        'return tonumber("5", 3)',
    ) == [LuaNil]
