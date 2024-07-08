from ast import literal_eval, parse, dump
from typing import NamedTuple, NewType

    
# class VariableSet(dict):
#     """dot.notation access to dictionary attributes"""
#     __getattr__ = dict.get
#     __setattr__ = dict.__setitem__
#     __delattr__ = dict.__delitem__


class VariableValue(NamedTuple):
    """This class defines a pair of dataype and value as a named tuple for more readable code"""
    datatype: str
    value: any

VariableSet = NewType("VariableSet", dict)

datatypes = {"list",
             "dict",
             "set",
             "integer",
             "float",
             "string",
             "boolean",
             "object"}

if __name__ == "__main__":
    local_vars = {}
    
    # all_vars: VariableSet[str, any] = VariableSet({})
    # local_vars: VariableSet[str, any] = VariableSet({"one": 1, "two": 2})
    # global_vars: VariableSet[str, any] = VariableSet({"a":41, "b": 42})
    # all_vars.update({"locals": local_vars})
    # all_vars.update({"globals": global_vars})
    # print(all_vars.locals.one)
    # print(all_vars.globals.b)
    # all_vars.globals.b = 45
    # print(all_vars.globals)
    # print(all_vars)
    # print(eval("all_vars.globals.a"))
    # print(eval("all_vars['globals']['a']"))
    # a = dict(all_vars)
    # print(type(a))
    # print(type(all_vars))
    # print(a['globals']['a'])
    # tree = parse("a['globals']['a']", mode='eval')
    # print(dump(tree))

