from __future__ import annotations

import locale as lc
import os
import subprocess
import sys
import tempfile
import time as py_time
import datetime

from ay.operations import str_to_lua_string
from ay.py2lua import lua_function, PyLuaWrapRet, py2lua, PyLuaRet
from ay.library.provider_abc import LibraryProvider
from ay.values import LuaTable, LuaString, LuaNil, LuaNumber, LuaBool, LuaValue

FAIL = LuaNil


def py_wday_to_lua_wday(x: int) -> int:
    if x == 7:
        return 1
    return x + 1


def get_day_number_of_year(date: datetime.date) -> int:
    return date.timetuple().tm_yday


def oserror_to_errtuple(e: OSError) -> list[LuaValue]:
    return [
        LuaNil,
        str_to_lua_string(e.strerror),
        LuaNumber(e.errno),
    ]


str_to_lc_category_map = {
    "all": lc.LC_ALL,
    "collate": lc.LC_COLLATE,
    "ctype": lc.LC_CTYPE,
    "monetary": lc.LC_MONETARY,
    "numeric": lc.LC_NUMERIC,
    "time": lc.LC_TIME,
}


def get_category_from_luastr(luastr: LuaString) -> int:
    string = luastr.content.decode("utf-8")
    return str_to_lc_category_map[string]


def os_table_generator() -> LuaTable:
    table = LuaTable()

    @lua_function(table, wrap_values=True)
    def clock() -> PyLuaWrapRet:
        # Returns an approximation of the amount in seconds of CPU time used by
        # the program, as returned by the underlying ISO C function clock.
        return [py_time.process_time()]

    @lua_function(table)
    def date(format=None, time=None, /) -> PyLuaRet:
        raise NotImplementedError()

    @lua_function(table)
    def difftime(t2, t1, /) -> PyLuaRet:
        raise NotImplementedError()

    @lua_function(table)
    def execute(command=None, /) -> PyLuaRet:
        # When called without a command, os.execute returns a boolean that is
        # true if a shell is available.
        if command is None:
            return [LuaBool(True)]

        # This function is equivalent to the ISO C function system.
        # It passes command to be executed by an operating system shell.
        assert isinstance(command, LuaString)
        retcode = subprocess.call(
            command.content.decode("utf-8"),
            shell=True,
        )
        # Its first result is true if the command terminated successfully,
        # or fail otherwise.
        # After this first result the function returns a string plus a number,
        # as follows:
        #     "exit": the command terminated normally; the following number is
        #             the exit status of the command.
        #     "signal": the command was terminated by a signal; the following
        #               number is the signal that terminated the command.
        return [
            LuaBool(True) if retcode == 0 else FAIL,
            str_to_lua_string("exit" if retcode >= 0 else "signal"),
            LuaNumber(abs(retcode)),
        ]

    @lua_function(table, name="exit")
    def exit_(code=None, close=None, /) -> PyLuaRet:
        # Calls the ISO C function exit to terminate the host program.
        # If code is true, the returned status is EXIT_SUCCESS;
        # if code is false, the returned status is EXIT_FAILURE;
        # if code is a number, the returned status is this number.
        # The default value for code is true.
        if code is None:
            code = 0
        elif isinstance(code, LuaNumber):
            code = code.value
        elif isinstance(code, LuaBool):
            code = 0 if code.true else 1
        else:
            raise NotImplementedError()

        # If the optional second argument close is true, the function closes the
        # Lua state before exiting (see lua_close).
        if close == LuaBool(True):
            sys.exit(code)
        else:
            os._exit(code)
        return []

    @lua_function(table)
    def getenv(varname, /) -> PyLuaRet:
        #  Returns the value of the process environment variable varname or fail
        #  if the variable is not defined.
        assert isinstance(varname, LuaString)
        value = os.getenv(varname.content.decode("utf-8"))
        if value is None:
            return [FAIL]
        return [str_to_lua_string(value)]

    @lua_function(table)
    def remove(filename, /) -> PyLuaRet:
        # Deletes the file (or empty directory, on POSIX systems) with the
        # given name.
        assert isinstance(filename, LuaString)
        try:
            os.unlink(filename.content)
        except OSError as e:
            # If this function fails, it returns fail plus a string describing
            # the error and the error code.
            return oserror_to_errtuple(e)
        # Otherwise, it returns true.
        return [LuaBool(True)]

    @lua_function(table)
    def rename(oldname, newname, /) -> PyLuaRet:
        # Renames the file or directory named oldname to newname.
        assert isinstance(oldname, LuaString)
        assert isinstance(newname, LuaString)
        try:
            os.rename(oldname.content, newname.content)
        except OSError as e:
            # If this function fails, it returns fail,
            # plus a string describing the error and the error code.
            return oserror_to_errtuple(e)
        # Otherwise, it returns true.
        return [LuaBool(True)]

    @lua_function(table)
    def setlocale(locale, category=None, /) -> PyLuaRet:
        # category is an optional string describing which category to change:
        # "all", "collate", "ctype", "monetary", "numeric", or "time";
        # the default category is "all".
        if category is None:
            category = lc.LC_ALL
        else:
            category = get_category_from_luastr(category)
        # When called with nil as the first argument, this function only returns
        # the name of the current locale for the given category.
        if locale is LuaNil:
            current_lc = lc.getlocale(category)
            return [
                py2lua(current_lc[0]),
                py2lua(current_lc[1]),
            ]

        # Sets the current locale of the program.
        # locale is a system-dependent string specifying a locale;
        assert isinstance(locale, LuaString)
        # If locale is the empty string, the current locale is set to an
        # implementation-defined native locale.
        if not locale.content:
            locale = None
        else:
            locale = locale.content.decode("utf-8")
        # If locale is the string "C", the current locale is set to the standard
        # C locale.
        try:
            new_locale_name = lc.setlocale(category, locale)
            # The function returns the name of the new locale,
            # or fail if the request cannot be honored.
        except lc.Error:
            return [FAIL]
        else:
            return [str_to_lua_string(new_locale_name)]

    @lua_function(table)
    def time(table=None, /) -> PyLuaRet:
        raise NotImplementedError()

    @lua_function(table)
    def tmpname() -> PyLuaRet:
        fd, name = tempfile.mkstemp(prefix="ay_", suffix="_ay")
        return [str_to_lua_string(name)]

    return table


class OSLibrary(LibraryProvider):
    def provide(self, table: LuaTable) -> None:
        table.put(LuaString(b"os"), os_table_generator())
