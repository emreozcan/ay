from __future__ import annotations

import enum
import io
import string
from abc import ABC, abstractmethod
from collections.abc import Sequence, Iterable, Callable
from typing import Literal, TYPE_CHECKING, Sequence

import attrs

import ay.values as ay_values
from ay.control_structures import BreakException, GotoException, ReturnException
from ay.values import (
    LuaNumber,
    LuaValue,
    LuaNumberType,
    LuaString,
    MAX_INT64,
    LuaTable,
    LuaFunction,
)
from ay.operations import (
    int_wrap_overflow,
    str_to_lua_string,
    adjust,
    coerce_to_bool,
    adjust_to_one,
    adjust_flatten,
)
import ay.operations as ay_operations

if TYPE_CHECKING:
    from ay.scope import Scope


def flatten(v: Iterable[LuaValue | Iterable[LuaValue]]) -> list[LuaValue]:
    result = []
    for elem in v:
        if isinstance(elem, Iterable):
            result.extend(flatten(elem))
        else:
            result.append(elem)
    return result


@attrs.define(slots=True)
class Node(ABC):
    pass


@attrs.define(slots=True)
class Terminal(Node):
    text: str


@attrs.define(slots=True)
class NonTerminal(Node, ABC):
    pass


@attrs.define(slots=True)
class AbstractSyntaxTree:
    root: Chunk


@attrs.define(slots=True)
class Chunk(NonTerminal):
    block: Block


@attrs.define(slots=True)
class Statement(NonTerminal, ABC):
    @abstractmethod
    def execute(self, scope: Scope) -> Sequence[LuaValue] | None:
        pass


@attrs.define(slots=True)
class Expression(NonTerminal, ABC):
    @abstractmethod
    def evaluate(self, scope: Scope) -> LuaValue | Sequence[LuaValue]:
        pass

    def evaluate_single(self, scope: Scope) -> LuaValue:
        return adjust_to_one(self.evaluate(scope))


@attrs.define(slots=True)
class ParenExpression(Expression):
    exp: Expression

    def evaluate(self, scope: Scope) -> LuaValue | Sequence[LuaValue]:
        return adjust_to_one(self.exp.evaluate(scope))


@attrs.define(slots=True)
class Block(Statement, Expression):
    def evaluate(self, scope: Scope) -> list[LuaValue]:
        return self.evaluate_without_inner_scope(scope.push())

    def execute(self, scope: Scope) -> Sequence[LuaValue] | None:
        return self.execute_without_inner_scope(scope.push())

    def evaluate_without_inner_scope(self, scope: Scope) -> list[LuaValue]:
        r = []
        for stmt in self.statements:
            r = stmt.execute(scope)
        return (
            flatten(
                expr.evaluate(scope) for expr in self.return_statement.values
            )
            if self.return_statement
            else r if r else []
        )

    def execute_without_inner_scope(self, scope: Scope) \
            -> Sequence[LuaValue] | None:
        v = None
        for stmt in self.statements:
            v = stmt.execute(scope)
        return v

    statements: Sequence[Statement]
    return_statement: ReturnStatement | None = None


@attrs.define(slots=True)
class Numeral(Expression, ABC):
    pass


@attrs.define(slots=True)
class NumeralHex(Numeral):
    digits: Terminal
    fract_digits: Terminal | None = None
    p_sign: Terminal | None = None
    p_digits: Terminal | None = None

    def evaluate(self, scope: Scope) -> LuaValue:
        if self.fract_digits or self.p_digits:
            if not self.p_sign:
                self.p_sign = Terminal("+")
            if not self.p_digits:
                self.p_digits = Terminal("0")
            if not self.fract_digits:
                self.fract_digits = Terminal("")
            whole_val = int(self.digits.text + self.fract_digits.text, 16)
            frac_val = whole_val / 16 ** len(self.fract_digits.text)
            exp_val = 2 ** int(self.p_sign.text + self.p_digits.text)
            return LuaNumber(frac_val * exp_val, LuaNumberType.FLOAT)
        # if the value overflows, it wraps around to fit into a valid integer.
        return int_wrap_overflow(int(self.digits.text, 16))


@attrs.define(slots=True)
class NumeralDec(Numeral):
    digits: Terminal
    fract_digits: Terminal | None = None
    e_sign: Terminal | None = None
    e_digits: Terminal | None = None

    def evaluate(self, scope: Scope) -> LuaValue:
        if self.fract_digits or self.e_digits:
            if not self.e_sign:
                self.e_sign = Terminal("+")
            if not self.e_digits:
                self.e_digits = Terminal("0")
            if not self.fract_digits:
                self.fract_digits = Terminal("0")
            return LuaNumber(
                float(
                    self.digits.text
                    + "."
                    + self.fract_digits.text
                    + "e"
                    + self.e_sign.text
                    + self.e_digits.text
                ),
                LuaNumberType.FLOAT,
            )
        whole_val = int(self.digits.text)
        if whole_val > MAX_INT64:
            return LuaNumber(float(self.digits.text), LuaNumberType.FLOAT)
        return LuaNumber(whole_val, LuaNumberType.INTEGER)


@attrs.define(slots=True)
class LiteralString(Expression):
    text: Terminal

    def _simple_string(self) -> LuaString:
        bytes_io = io.BytesIO()
        currently_skipping_whitespace = False
        currently_reading_decimal = False
        currently_read_decimal: str = ""
        str_iter = iter(self.text.text[1:-1])
        for character in str_iter:
            if currently_skipping_whitespace:
                if character in string.whitespace:
                    continue
                currently_skipping_whitespace = False
            if currently_reading_decimal:
                if (
                    character in string.digits
                    and len(currently_read_decimal) < 3
                ):
                    currently_read_decimal += character
                    continue
                bytes_io.write(bytes([int(currently_read_decimal)]))
                currently_reading_decimal = False
                currently_read_decimal = ""
            if character == "\\":
                try:
                    escape_char = next(str_iter)
                except StopIteration:
                    bytes_io.write(b"\\")
                    break
                if escape_char == "a":
                    bytes_io.write(b"\a")
                elif escape_char == "b":
                    bytes_io.write(b"\b")
                elif escape_char == "f":
                    bytes_io.write(b"\f")
                elif escape_char == "n":
                    bytes_io.write(b"\n")
                elif escape_char == "r":
                    bytes_io.write(b"\r")
                elif escape_char == "t":
                    bytes_io.write(b"\t")
                elif escape_char == "v":
                    bytes_io.write(b"\v")
                elif escape_char == "\\":
                    bytes_io.write(b"\\")
                elif escape_char == '"':
                    bytes_io.write(b'"')
                elif escape_char == "'":
                    bytes_io.write(b"'")
                elif escape_char == "\n":
                    bytes_io.write(b"\n")
                elif escape_char == "z":
                    currently_skipping_whitespace = True
                    continue
                elif escape_char == "x":
                    try:
                        hex_digit_1 = next(str_iter)
                        hex_digit_2 = next(str_iter)
                    except StopIteration:
                        raise NotImplementedError()
                    bytes_io.write(bytes.fromhex(hex_digit_1 + hex_digit_2))
                elif escape_char in string.digits:
                    currently_reading_decimal = True
                    currently_read_decimal = escape_char
                    continue
                elif escape_char == "u":
                    left_brace = next(str_iter)
                    if left_brace != "{":
                        raise NotImplementedError()
                    hex_digits = []
                    while True:
                        hex_digit = next(str_iter)
                        if hex_digit == "}":
                            break
                        hex_digits.append(hex_digit)
                    hex_str = "".join(hex_digit)
                    bytes_io.write(chr(int(hex_str, 16)).encode("utf-8"))
                else:
                    raise NotImplementedError()
                continue
            bytes_io.write(character.encode("utf-8"))
        bytes_io.seek(0)
        return LuaString(bytes_io.read())

    def _long_bracket(self) -> LuaString:
        # Literals in this bracketed form can run for several lines,
        # do not interpret any escape sequences,
        # and ignore long brackets of any other level.
        level = 1
        while self.text.text[level] == "=":
            level += 1
        level -= 1
        # [====[...
        #   0123456
        # ...]====]
        # (-)654321
        symbol_len = level + 2
        bytes_io = io.BytesIO()
        str_iter = iter(self.text.text[symbol_len:-symbol_len])
        converting_end_of_line = False
        first_character_seen = False
        for character in str_iter:
            # Any kind of end-of-line sequence (carriage return, newline,
            # carriage return followed by newline, or newline followed by
            # carriage return) is converted to a simple newline.
            if character in ("\r", "\n"):
                if not first_character_seen:
                    # When the opening long bracket is immediately followed by a
                    # newline, the newline is not included in the string.
                    converting_end_of_line = True
                    first_character_seen = True
                    continue
                if converting_end_of_line:
                    continue
                first_character_seen = True
                converting_end_of_line = True
                bytes_io.write(b"\n")
                continue
            else:
                first_character_seen = True
                converting_end_of_line = False
                bytes_io.write(character.encode("utf-8"))
        bytes_io.seek(0)
        return LuaString(bytes_io.read())

    def evaluate(self, scope: Scope) -> LuaString:
        if self.text.text[0] != "[":
            return self._simple_string()
        return self._long_bracket()


@attrs.define(slots=True)
class LiteralFalse(Expression):
    def evaluate(self, scope: Scope) -> LuaValue:
        return ay_values.LuaBool(False)


@attrs.define(slots=True)
class LiteralTrue(Expression):
    def evaluate(self, scope: Scope) -> LuaValue:
        return ay_values.LuaBool(True)


@attrs.define(slots=True)
class LiteralNil(Expression):
    def evaluate(self, scope: Scope) -> LuaValue:
        return ay_values.LuaNil


@attrs.define(slots=True)
class Name(NonTerminal):
    name: Terminal

    def as_lua_string(self):
        return str_to_lua_string(self.name.text)


@attrs.define(slots=True)
class VarArgExpr(Expression):
    def evaluate(self, scope: Scope) -> LuaValue | Sequence[LuaValue]:
        v = scope.get_varargs()
        if v is not None:
            return v
        raise NotImplementedError()


@attrs.define(slots=True)
class Variable(Expression, ABC):
    pass


@attrs.define(slots=True)
class VarName(Variable):
    def evaluate(self, scope: Scope) -> LuaValue:
        return scope.get_ls(str_to_lua_string(self.name.name.text))

    name: Name


@attrs.define(slots=True)
class VarIndex(Variable):
    def evaluate(self, scope: Scope) -> LuaValue:
        table = self.base.evaluate(scope)
        assert isinstance(table, LuaTable)
        return table.get(self.index.evaluate_single(scope))

    base: Expression
    index: Expression


@attrs.define(slots=True)
class TableConstructor(Expression):
    fields: Sequence[Field]

    def evaluate(self, scope: Scope) -> LuaValue:
        table = LuaTable()
        if not self.fields:
            return table
        counter = 1
        # If the last field in the list has the form exp and the expression is a
        # multires expression,
        # then all values returned by this expression enter the list
        # consecutively (see §3.4.12).
        last_field = self.fields[-1]
        if last_field and isinstance(last_field, FieldCounterKey):
            field_iter = iter(self.fields[:-1])
        else:
            field_iter = iter(self.fields)
        for field in field_iter:
            if isinstance(field, FieldWithKey):
                if isinstance(field.key, Name):
                    key = str_to_lua_string(field.key.name.text)
                elif isinstance(field.key, Expression):
                    key = field.key.evaluate_single(scope)
                else:
                    raise NotImplementedError(f"{type(field.key)=}")
                table.put(key, field.value.evaluate_single(scope))
            elif isinstance(field, FieldCounterKey):
                key = LuaNumber(counter, LuaNumberType.INTEGER)
                counter += 1
                table.put(key, field.value.evaluate_single(scope))
            else:
                raise NotImplementedError(f"{type(field)=}")
        if last_field and isinstance(last_field, FieldCounterKey):
            last_field_value = last_field.value.evaluate(scope)
            if isinstance(last_field_value, list):
                for counter, val in enumerate(last_field_value, start=counter):
                    table.put(
                        LuaNumber(counter, LuaNumberType.INTEGER),
                        val,
                    )
            else:
                table.put(
                    LuaNumber(counter, LuaNumberType.INTEGER),
                    last_field_value,
                )
        return table


@attrs.define(slots=True)
class Field(NonTerminal, ABC):
    value: Expression


@attrs.define(slots=True)
class FieldWithKey(Field):
    key: Expression | Name | None = None


@attrs.define(slots=True)
class FieldCounterKey(Field):
    pass


@attrs.define(slots=True)
class Parlist(NonTerminal):
    names: Sequence[Name]
    vararg: bool = False


@attrs.define(slots=True)
class FuncBody(Expression):
    params: Sequence[Name]
    body: Block
    vararg: bool = False

    def evaluate(self, scope: Scope) -> LuaFunction:
        return LuaFunction(
            param_names=[p.as_lua_string() for p in self.params],
            variadic=self.vararg,
            block=self.body,
            parent_scope=scope,
            gets_scope=False,
            min_req=0,  # The parameters get adjusted.
        )


@attrs.define(slots=True)
class FuncDef(Expression):
    body: FuncBody

    def evaluate(self, scope: Scope) -> LuaValue:
        return self.body.evaluate(scope)


@attrs.define(slots=True)
class FuncCallRegular(Expression, Statement):
    def evaluate(self, scope: Scope) -> list[LuaValue]:
        function = self.name.evaluate(scope)
        assert isinstance(function, LuaFunction)
        args = [arg.evaluate(scope) for arg in self.args]
        return function.call(args, scope)

    def execute(self, scope: Scope) -> None | list[LuaValue]:
        r = self.evaluate(scope)
        if r:
            return r
        return None

    name: Expression
    args: Sequence[Expression]


@attrs.define(slots=True)
class FuncCallMethod(Expression, Statement):
    def evaluate(self, scope: Scope) -> Sequence[LuaValue]:
        # A call v:name(args) is syntactic sugar for v.name(v,args),
        # except that v is evaluated only once.
        v = self.object.evaluate(scope)
        assert isinstance(v, LuaTable)
        function = v.get(str_to_lua_string(self.method.name.text))
        assert isinstance(function, LuaFunction)
        args = [arg.evaluate(scope) for arg in self.args]
        return function.call(args, scope)

    def execute(self, scope: Scope) -> None | list[LuaValue]:
        try:
            self.evaluate(scope)
        except ReturnException as re:
            return re.values

    object: Expression
    method: Name
    args: Sequence[Expression]


class UnaryOperator(enum.Enum):
    NEG = "-"
    NOT = "not"
    LENGTH = "#"
    BIT_NOT = "~"


unary_operator_functions: dict[
    UnaryOperator,
    Callable[[LuaValue], LuaValue]
] = {
    UnaryOperator.NEG: ay_operations.arith_unary_minus,
    UnaryOperator.NOT: ay_operations.logical_unary_not,
    UnaryOperator.LENGTH: ay_operations.length,
    UnaryOperator.BIT_NOT: ay_operations.bitwise_unary_not,
}


@attrs.define(slots=True)
class UnaryOperation(Expression):
    op: UnaryOperator
    exp: Expression

    def evaluate(self, scope: Scope) -> LuaValue:
        v = self.exp.evaluate(scope)
        return unary_operator_functions[self.op](v)


class BinaryOperator(enum.Enum):
    OR = "or"
    AND = "and"
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "=="
    NE = "~="
    BIT_OR = "|"
    BIT_XOR = "~"
    BIT_AND = "&"
    SHIFT_LEFT = "<<"
    SHIFT_RIGHT = ">>"
    CONCAT = ".."
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    FLOAT_DIV = "/"
    FLOOR_DIV = "//"
    MODULO = "%"
    EXP = "^"


binary_operator_functions: dict[
    BinaryOperator,
    Callable[[LuaValue, LuaValue], LuaValue]
] = {
    BinaryOperator.LT: ay_operations.rel_lt,
    BinaryOperator.LE: ay_operations.rel_le,
    BinaryOperator.GT: ay_operations.rel_gt,
    BinaryOperator.GE: ay_operations.rel_ge,
    BinaryOperator.EQ: ay_operations.rel_eq,
    BinaryOperator.NE: ay_operations.rel_ne,
    BinaryOperator.BIT_OR: ay_operations.bitwise_or,
    BinaryOperator.BIT_XOR: ay_operations.bitwise_xor,
    BinaryOperator.BIT_AND: ay_operations.bitwise_and,
    BinaryOperator.SHIFT_LEFT: ay_operations.bitwise_shift_left,
    BinaryOperator.SHIFT_RIGHT: ay_operations.bitwise_shift_right,
    BinaryOperator.CONCAT: ay_operations.concat,
    BinaryOperator.ADD: ay_operations.arith_add,
    BinaryOperator.SUBTRACT: ay_operations.arith_sub,
    BinaryOperator.MULTIPLY: ay_operations.arith_mul,
    BinaryOperator.FLOAT_DIV: ay_operations.arith_float_div,
    BinaryOperator.FLOOR_DIV: ay_operations.arith_floor_div,
    BinaryOperator.MODULO: ay_operations.arith_mod,
    BinaryOperator.EXP: ay_operations.arith_exp,
}



@attrs.define(slots=True)
class BinaryOperation(Expression, ABC):
    lhs: Expression
    op: BinaryOperator
    rhs: Expression

    def evaluate(self, scope: Scope) -> LuaValue:
        op = self.op
        # Both and and or use short-circuit evaluation;
        # that is, the second operand is evaluated only if necessary.
        if op == BinaryOperator.AND:
            # The conjunction operator "and" returns its first argument if this
            # value is false or nil;
            l_val = self.lhs.evaluate_single(scope)
            if l_val is ay_values.LuaNil or l_val == ay_values.LuaBool(False):
                return l_val
            # otherwise, and returns its second argument.
            return self.rhs.evaluate_single(scope)
        if op == BinaryOperator.OR:
            # The disjunction operator "or" returns its first argument if this
            # value is different from nil and false;
            l_val = self.lhs.evaluate_single(scope)
            if (
                l_val is not ay_values.LuaNil
                and l_val != ay_values.LuaBool(False)
            ):
                return l_val
            # otherwise, or returns its second argument.
            return self.rhs.evaluate_single(scope)

        left = self.lhs.evaluate_single(scope)
        right = self.rhs.evaluate_single(scope)
        return binary_operator_functions[op](left, right)


@attrs.define(slots=True)
class ReturnStatement(NonTerminal):
    values: Sequence[Expression]


@attrs.define(slots=True)
class EmptyStatement(Statement):
    def execute(self, scope: Scope) -> None:
        pass


@attrs.define(slots=True)
class Assignment(Statement):
    def execute(self, scope: Scope) -> list[LuaValue]:
        values = adjust(
            [expr.evaluate(scope) for expr in self.exprs], len(self.names)
        )
        for variable, value in zip(self.names, values):
            if isinstance(variable, VarName):
                var_name = str_to_lua_string(variable.name.name.text)
                scope.put_nonlocal_ls(var_name, value)
            elif isinstance(variable, VarIndex):
                table = variable.base.evaluate(scope)
                assert isinstance(table, LuaTable)
                table.put(variable.index.evaluate(scope), value)
            else:
                raise NotImplementedError(f"{type(variable)=}")
        return values

    names: Sequence[Variable]
    exprs: Sequence[Expression]


@attrs.define(slots=True)
class Label(Statement):
    def execute(self, scope: Scope) -> None:
        raise NotImplementedError()

    name: Name


@attrs.define(slots=True)
class Break(Statement):
    def execute(self, scope: Scope) -> None:
        raise BreakException()


@attrs.define(slots=True)
class Goto(Statement):
    def execute(self, scope: Scope) -> None:
        raise GotoException(self.name)

    name: Name


@attrs.define(slots=True)
class Do(Statement):
    def execute(self, scope: Scope) -> None:
        self.block.execute(scope)

    block: Block


@attrs.define(slots=True)
class While(Statement):
    def execute(self, scope: Scope) -> None:
        new_vm = scope.push()
        try:
            while coerce_to_bool(self.condition.evaluate(scope)).true:
                self.block.execute_without_inner_scope(new_vm)
        except BreakException:
            pass

    condition: Expression
    block: Block


@attrs.define(slots=True)
class Repeat(Statement):
    def execute(self, scope: Scope) -> None:
        new_vm = scope.push()
        try:
            while True:
                self.block.execute_without_inner_scope(new_vm)
                if coerce_to_bool(self.condition.evaluate(new_vm)).true:
                    break
        except BreakException:
            pass

    block: Block
    condition: Expression


@attrs.define(slots=True)
class If(Statement):
    def execute(self, scope: Scope) -> None:
        for cnd, blk in self.blocks:
            if coerce_to_bool(cnd.evaluate(scope)).true:
                blk.execute(scope)
                return
        if self.else_block:
            self.else_block.execute(scope)

    blocks: Sequence[tuple[Expression, Block]]
    else_block: Block | None = None


@attrs.define(slots=True)
class For(Statement):
    name: Name
    start: Expression
    stop: Expression
    step: Expression | None
    block: Block

    def execute(self, scope: Scope) -> None:
        try:
            self._execute(scope)
        except BreakException:
            pass

    def _execute(self, scope: Scope) -> None:
        # This for loop is the "numerical" for loop explained in 3.3.5.
        # The given identifier (Name) defines the control variable,
        # which is a new variable local to the loop body (block).
        control_varname = self.name.as_lua_string()
        # The loop starts by evaluating once the three control expressions.
        # Their values are called respectively
        # the initial value,
        initial_value = adjust_to_one(self.start.evaluate(scope))
        assert isinstance(initial_value, LuaNumber)
        # the limit,
        limit = adjust_to_one(self.stop.evaluate(scope))
        assert isinstance(limit, LuaNumber)
        # and the step. If the step is absent, it defaults to 1.
        if self.step:
            step = adjust_to_one(self.step.evaluate(scope))
            assert isinstance(step, LuaNumber)
        else:
            step = LuaNumber(1, LuaNumberType.INTEGER)
        # If both the initial value and the step are integers,
        # the loop is done with integers;
        # note that the limit may not be an integer.
        is_integer_loop = (
            initial_value.type == LuaNumberType.INTEGER
            and step.type == LuaNumberType.INTEGER
        )
        if not is_integer_loop:
            # Otherwise, the three values are converted to floats
            # and the loop is done with floats.
            initial_value = ay_operations.coerce_int_to_float(initial_value)
            limit = ay_operations.coerce_int_to_float(limit)
            step = ay_operations.coerce_int_to_float(step)
        # After that initialization, the loop body is repeated with the value of
        # the control variable going through an arithmetic progression,
        # starting at the initial value,
        # with a common difference given by the step.
        # A negative step makes a decreasing sequence;
        # a step equal to zero raises an error.
        if step.value == 0:
            raise NotImplementedError()
        # The loop continues while the value is less than or equal to the limit
        # (greater than or equal to for a negative step).
        # If the initial value is already greater than the limit
        # (or less than, if the step is negative),
        # the body is not executed.
        is_step_negative = step.value < 0
        condition_func = (
            ay_operations.rel_ge if is_step_negative else ay_operations.rel_le
        )
        # For integer loops, the control variable never wraps around; instead,
        # the loop ends in case of an overflow.
        # You should not change the value of the control variable during the
        # loop.
        # If you need its value after the loop, assign it to another variable
        # before exiting the loop.
        control_val = initial_value
        inner_scope = scope.push()
        while condition_func(control_val, limit).true:
            inner_scope.put_local_ls(
                control_varname,
                ay_values.Variable(control_val)
            )
            self.block.execute_without_inner_scope(inner_scope)
            overflow, control_val = ay_operations.overflow_arith_add(
                control_val, step
            )
            if overflow and is_integer_loop:
                break


@attrs.define(slots=True)
class ForIn(Statement):
    names: Sequence[Name]
    exprs: Sequence[Expression]
    block: Block

    def execute(self, scope: Scope) -> None:
        try:
            self._execute(scope)
        except BreakException:
            pass

    def _execute(self, outer_scope: Scope) -> None:
        # The generic for statement works over functions, called iterators.
        # On each iteration, the iterator function is called to produce a new
        # value, stopping when this new value is nil.

        #  A for statement like
        #      for var_1, ···, var_n in explist do body end
        # works as follows.
        # The names var_i declare loop variables local to the loop body.
        body_scope = outer_scope.push()
        name_count = len(self.names)
        names = [name.as_lua_string() for name in self.names]
        for name in names:
            body_scope.put_local_ls(
                name, ay_values.Variable(ay_values.LuaNil)
            )
        # The first of these variables is the control variable.
        control_variable_name = names[0]
        # The loop starts by evaluating explist to produce four values:
        exp_vals = adjust([exp.evaluate(outer_scope) for exp in self.exprs], 4)
        # an iterator function,
        iterator_function = exp_vals[0]
        if not isinstance(iterator_function, LuaFunction):
            raise NotImplementedError()
        # a state,
        state = exp_vals[1]
        # an initial value for the control variable,
        initial_value = exp_vals[2]
        body_scope.put_local_ls(
            control_variable_name, ay_values.Variable(initial_value)
        )
        # and a closing value.
        closing_value = exp_vals[3]

        nil = ay_values.LuaNil
        while True:
            # Then, at each iteration, Lua calls the iterator function with two
            # arguments: the state and the control variable.
            results = adjust(
                iterator_function.call(
                    [state, body_scope.get_ls(control_variable_name)],
                    outer_scope
                ),
                name_count,
            )
            # The results from this call are then assigned to the loop
            # variables, following the rules of multiple assignments.
            for name, value in zip(names, results):
                body_scope.put_local_ls(name, ay_values.Variable(value))
            # If the control variable becomes nil, the loop terminates.
            if results[0] is nil:
                break
            # Otherwise, the body is executed and the loop goes to the next
            # iteration.
            self.block.execute_without_inner_scope(body_scope)
            continue
        if closing_value is not nil:
            # The closing value behaves like a to-be-closed variable,
            # which can be used to release resources when the loop ends.
            # Otherwise, it does not interfere with the loop.
            raise NotImplementedError()


@attrs.define(slots=True)
class FuncName(NonTerminal):
    names: Sequence[Name]
    method: bool


@attrs.define(slots=True)
class FunctionStatement(Statement):
    name: FuncName
    body: FuncBody

    def execute(self, scope: Scope) -> list[LuaFunction]:
        function = self.body.evaluate(scope)
        if self.name.method:
            function.param_names.insert(0, LuaString(b"self"))
        if len(self.name.names) == 1:
            name = self.name.names[0].as_lua_string()
            function.name = name
            scope.put_nonlocal_ls(name, function)
        else:
            table = scope.get_ls(self.name.names[0].as_lua_string())
            for name in self.name.names[1:-1]:
                table = table.get(name.as_lua_string())
                assert isinstance(table, LuaTable)
            function.name = self.name.names[-1].as_lua_string()
            table.put(function.name, function)
        return [function]


@attrs.define(slots=True)
class LocalFunctionStatement(Statement):
    name: Name
    body: FuncBody

    def execute(self, scope: Scope) -> list[LuaFunction]:
        # The statement
        #      local function f () body end
        # translates to
        #      local f; f = function () body end
        # not to
        #      local f = function () body end
        # (This only makes a difference
        # when the body of the function contains references to f.)
        name = self.name.as_lua_string()
        scope.put_local_ls(name, ay_values.Variable(ay_values.LuaNil))
        function = self.body.evaluate(scope)
        function.name = name
        scope.put_local_ls(name, ay_values.Variable(function))
        return [function]


@attrs.define(slots=True)
class AttributeName(NonTerminal):
    name: Name
    attrib: Name | None = None


@attrs.define(slots=True)
class LocalAssignment(Statement):
    names: Sequence[AttributeName]
    exprs: Sequence[Expression]

    def execute(self, scope: Scope) -> list[LuaValue]:
        if self.exprs:
            exp_vals = [exp.evaluate(scope) for exp in self.exprs]
            exp_vals = adjust(exp_vals, len(self.names))
        else:
            exp_vals = [ay_values.LuaNil] * len(self.names)
        used_closed = False
        for attname, exp_val in zip(self.names, exp_vals):
            var_name = attname.name.as_lua_string()
            if attname.attrib is None:
                scope.put_local_ls(var_name, ay_values.Variable(exp_val))
            else:
                attrib = attname.attrib.as_lua_string()
                if attrib.content == b"close":
                    if used_closed:
                        raise NotImplementedError()
                    used_closed = True
                    scope.put_local_ls(
                        var_name, ay_values.Variable(exp_val, to_be_closed=True)
                    )
                elif attrib.content == b"const":
                    scope.put_local_ls(
                        var_name, ay_values.Variable(exp_val, constant=True)
                    )
                else:
                    # TODO: Create an error
                    raise NotImplementedError()
        return exp_vals


@attrs.define(slots=True)
class ParsedLiteralLuaStringExpr(Expression):
    """
    Not included in the Lua grammar.
    Used when a part of an expression which results in a LuaString is parsed.
    For example, the "b" in ``a.b = 1``.
    (Which is transformed to be equivalent to ``a["b"] = 1``.)
    """
    value: LuaString

    def evaluate(self, scope: Scope) -> LuaValue | Sequence[LuaValue]:
        return self.value
