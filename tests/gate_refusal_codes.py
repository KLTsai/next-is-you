"""Every refusal code the send gate's source can answer Start or Stop with (#146).

Start answers a dict, where `{"error": code}` is a refusal. Stop answers a bare
string, either a visit state or a refusal code. The reader follows what those
functions return and fails on any form it does not know, so a new way of
answering cannot slip past the catalog test. Teach it the new form, or add the
new Start function to `START_FUNCTIONS`.
"""

from __future__ import annotations

import ast
from typing import Iterator

# Every function whose return value is, or becomes, the answer to Start.
START_FUNCTIONS = ("start_visit", "_start_visit", "_preflight_validate")
STOP_FUNCTION = "stop_visit"
# What Stop returns that is not a refusal: these states, and a variable assigned
# only from this call, which reports the visit's state.
STOP_STATES = frozenset({"stopping", "stopped"})
STOP_STATE_SOURCE = "await repository.stop("

Function = ast.FunctionDef | ast.AsyncFunctionDef


def gate_refusal_codes(source: str) -> set[str]:
    return _Gate(ast.parse(source)).refusal_codes()


class _Gate:
    def __init__(self, module: ast.Module) -> None:
        self.module = module
        self.parents = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }
        self.tables = {
            statement.targets[0].id: statement.value
            for statement in module.body
            if isinstance(statement, ast.Assign)
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Dict)
        }
        self.helpers = {
            statement.name: statement
            for statement in module.body
            if isinstance(statement, ast.FunctionDef)
        }

    def refusal_codes(self) -> set[str]:
        codes: set[str] = set()
        for name in START_FUNCTIONS:
            function = self._function(name)
            for value in _returned(function):
                codes |= self._start_answer(function, value)
        stop = self._function(STOP_FUNCTION)
        for value in _returned(stop):
            codes |= self._stop_answer(stop, value)
        return codes

    def _function(self, name: str) -> Function:
        [function] = [
            node
            for node in ast.walk(self.module)
            if isinstance(node, Function) and node.name == name
        ]
        return function

    def _start_answer(self, function: Function, node: ast.expr) -> set[str]:
        """The codes in a dict a Start function returns, or builds to return."""
        match node:
            case ast.Dict(keys=keys, values=values):
                codes: set[str] = set()
                for key, value in zip(keys, values):
                    if _key(key) == "error":
                        codes |= self._codes(value)
                return codes
            case ast.Await(
                value=ast.Call(func=ast.Attribute(value=ast.Name(id="self"), attr=name))
            ) if name in START_FUNCTIONS:
                return set()  # That function's own returns are read.
            case ast.Name(id=name):
                return self._returned_variable(function, name)
        raise _unreadable(node)

    def _returned_variable(self, function: Function, name: str) -> set[str]:
        """Every use of a returned variable: what it is given, and what is added."""
        codes: set[str] = set()
        for use in _uses(function, name):
            parent = self.parents[use]
            match parent:
                case ast.Assign(targets=[target], value=value) if target is use:
                    codes |= self._start_answer(function, value)
                case ast.AnnAssign(value=ast.expr() as value) if parent.target is use:
                    codes |= self._start_answer(function, value)
                case ast.Subscript() if isinstance(parent.ctx, ast.Load):
                    pass
                case ast.Subscript(slice=key):
                    match self.parents[parent]:
                        case ast.Assign(targets=[target], value=value) if (
                            target is parent
                        ):
                            if _key(key) == "error":
                                codes |= self._codes(value)
                        case statement:
                            raise _unreadable(statement)
                case ast.Attribute(attr="get") | ast.Return() | ast.Compare():
                    pass
                case _:
                    raise _unreadable(parent)
        return codes

    def _stop_answer(self, stop: Function, node: ast.expr) -> set[str]:
        match node:
            case ast.Constant(value=None):
                return set()  # No such visit; the worker answers for it.
            case ast.Constant(value=state) if state in STOP_STATES:
                return set()
            case ast.Name(id=name):
                assigned = [
                    self.parents[use]
                    for use in _uses(stop, name)
                    if isinstance(use.ctx, ast.Store)
                ]
                if assigned and all(
                    isinstance(statement, ast.Assign)
                    and ast.unparse(statement.value).startswith(STOP_STATE_SOURCE)
                    for statement in assigned
                ):
                    return set()
                raise _unreadable(node)
        return self._codes(node)

    def _codes(self, node: ast.expr) -> set[str]:
        """The codes an expression can evaluate to."""
        match node:
            case ast.Constant(value=str(code)):
                return {code}
            case ast.Subscript(value=ast.Name(id=name)) if name in self.tables:
                return self._table_codes(name)
            case ast.Call(
                func=ast.Attribute(value=ast.Name(id=name), attr="get"),
                args=[_, default],
            ) if name in self.tables:
                return self._table_codes(name) | self._codes(default)
            case ast.Call(func=ast.Name(id=name)) if name in self.helpers:
                return set().union(
                    *(self._codes(value) for value in _returned(self.helpers[name]))
                )
        raise _unreadable(node)

    def _table_codes(self, name: str) -> set[str]:
        """A module table's values, once nothing else can add to them."""
        for use in _uses(self.module, name):
            parent = self.parents[use]
            match parent:
                case ast.Assign() if self.parents[parent] is self.module:
                    continue
                case ast.Subscript(ctx=ast.Load()) | ast.Attribute(attr="get"):
                    continue
            raise _unreadable(parent)
        return set().union(*(self._codes(value) for value in self.tables[name].values))


def _key(node: ast.expr | None) -> str:
    """A dict key, which must be written out to tell whether it is `error`."""
    match node:
        case ast.Constant(value=str(key)):
            return key
        case None:
            raise AssertionError("cannot read a dict spread into a gate answer")
    raise _unreadable(node)


def _uses(scope: ast.AST, name: str) -> Iterator[ast.Name]:
    return (
        node
        for node in ast.walk(scope)
        if isinstance(node, ast.Name) and node.id == name
    )


def _returned(function: Function) -> list[ast.expr]:
    """The expressions a function returns; a bare `return` returns none."""
    return [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Return) and node.value is not None
    ]


def _unreadable(node: ast.AST) -> AssertionError:
    return AssertionError(
        f"cannot read the gate answer on line {node.lineno}: {ast.unparse(node)}"
    )
