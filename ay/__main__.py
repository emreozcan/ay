from . import lua_parser, LuaInterpreter


def main():
    text = """
function f(x)
    return 10 * x, 20 * x
end

a, b = f(1)
c, d = (f(1))
print(a, b)
print(c, d)
"""

    print("\n".join([f"> {line}" for line in text[1:].splitlines()]))
    print()

    parsed_lua = lua_parser.parse(text)
    # print(f"Parse tree:\n{parsed_lua.pretty()}")

    lua_interpreter = LuaInterpreter()
    ret_val = lua_interpreter.visit(parsed_lua)
    if ret_val:
        print("[" + ", ".join(str(x) for x in ret_val) + "]")


if __name__ == "__main__":
    main()
