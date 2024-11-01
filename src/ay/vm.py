from __future__ import annotations

import sys

import attrs

from ay.global_table import create_global_table
from ay.scope import Scope, AnyPath
from ay.values import (
    LuaTable,
    LuaString,
    Variable,
    LuaValue, )


@attrs.define(slots=True, repr=False, init=False)
class VirtualMachine:
    globals: LuaTable
    root_scope: Scope
    emitting_warnings: bool = False

    def __init__(self):
        self.globals = create_global_table()
        self.root_scope = Scope(self, None)

    def eval(self, expr: str):
        return self.root_scope.eval(expr)

    def exec(self, chunk: str) -> list[LuaValue]:
        return self.root_scope.exec(chunk)

    def exec_file(self, file_path: AnyPath) -> list[LuaValue]:
        return self.root_scope.exec_file(file_path)

    def has_ls(self, key: LuaString):
        assert isinstance(key, LuaString)
        return self.root_scope.has_ls(key) or self.globals.has(key)

    def get_ls(self, key: LuaString):
        assert isinstance(key, LuaString)
        if self.root_scope.has_ls(key):
            return self.root_scope.get_ls(key)
        return self.globals.get(key)

    def put_local_ls(self, key: LuaString, variable: Variable):
        assert isinstance(key, LuaString)
        assert isinstance(variable, Variable)
        self.root_scope.put_local_ls(key, variable)

    def put_nonlocal_ls(self, key: LuaString, variable: Variable | LuaValue):
        assert isinstance(key, LuaString)
        if isinstance(variable, Variable):
            assert not variable.constant
            assert not variable.to_be_closed
            self.globals.put(key, variable.value)
            return
        elif isinstance(variable, LuaValue):
            self.globals.put(key, variable)
            return
        assert False

    def get_warning(self, *messages: str | bytes | LuaString):
        if self.emitting_warnings:
            print(f"Warning: ", *messages, sep="", file=sys.stderr)
