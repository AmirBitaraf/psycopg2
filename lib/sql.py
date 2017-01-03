"""SQL composition utility module
"""

# psycopg/sql.py - Implementation of the JSON adaptation objects
#
# Copyright (C) 2016 Daniele Varrazzo  <daniele.varrazzo@gmail.com>
#
# psycopg2 is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# In addition, as a special exception, the copyright holders give
# permission to link this program with the OpenSSL library (or with
# modified versions of OpenSSL that use the same license as OpenSSL),
# and distribute linked combinations including the two.
#
# You must obey the GNU Lesser General Public License in all respects for
# all of the code used other than OpenSSL.
#
# psycopg2 is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public
# License for more details.

import sys
import string

from psycopg2 import extensions as ext


_formatter = string.Formatter()


class Composable(object):
    """
    Abstract base class for objects that can be used to compose an SQL string.

    `!Composable` objects can be passed directly to `~cursor.execute()` and
    `~cursor.executemany()`.

    `!Composable` objects can be joined using the ``+`` operator: the result
    will be a `Composed` instance containing the objects joined. The operator
    ``*`` is also supported with an integer argument: the result is a
    `!Composed` instance containing the left argument repeated as many times as
    requested.

    .. automethod:: as_string
    """
    def as_string(self, conn_or_curs):
        """
        Return the string value of the object.

        The object is evaluated in the context of the *conn_or_curs* argument.

        The function is automatically invoked by `~cursor.execute()` and
        `~cursor.executemany()` if a `!Composable` is passed instead of the
        query string.
        """
        raise NotImplementedError

    def __add__(self, other):
        if isinstance(other, Composed):
            return Composed([self]) + other
        if isinstance(other, Composable):
            return Composed([self]) + Composed([other])
        else:
            return NotImplemented

    def __mul__(self, n):
        return Composed([self] * n)


class Composed(Composable):
    """
    A `Composable` object obtained concatenating a sequence of `Composable`.

    The object is usually created using `Composable` operators. However it is
    possible to create a `!Composed` directly specifying a sequence of
    `Composable` as arguments.

    Example::

        >>> comp = sql.Composed(
        ...     [sql.SQL("insert into "), sql.Identifier("table")])
        >>> print(comp.as_string(conn))
        insert into "table"

    .. automethod:: join
    """
    def __init__(self, seq):
        self._seq = []
        for i in seq:
            if not isinstance(i, Composable):
                raise TypeError(
                    "Composed elements must be Composable, got %r instead" % i)
            self._seq.append(i)

    def __repr__(self):
        return "sql.Composed(%r)" % (self._seq,)

    def as_string(self, conn_or_curs):
        rv = []
        for i in self._seq:
            rv.append(i.as_string(conn_or_curs))
        return ''.join(rv)

    def __add__(self, other):
        if isinstance(other, Composed):
            return Composed(self._seq + other._seq)
        if isinstance(other, Composable):
            return Composed(self._seq + [other])
        else:
            return NotImplemented

    def join(self, joiner):
        """
        Return a new `!Composed` interposing the *joiner* with the `!Composed` items.

        The *joiner* must be a `SQL` or a string which will be interpreted as
        an `SQL`.

        Example::

            >>> fields = sql.Identifier('foo') + sql.Identifier('bar')  # a Composed
            >>> print(fields.join(', ').as_string(conn))
            "foo", "bar"

        """
        if isinstance(joiner, basestring):
            joiner = SQL(joiner)
        elif not isinstance(joiner, SQL):
            raise TypeError(
                "Composed.join() argument must be a string or an SQL")

        if len(self._seq) <= 1:
            return self

        it = iter(self._seq)
        rv = [it.next()]
        for i in it:
            rv.append(joiner)
            rv.append(i)

        return Composed(rv)


class SQL(Composable):
    """
    A `Composable` representing a snippet of SQL statement.

    `!SQL` exposes `join()` and `format()` methods useful to create a template
    where to merge variable parts of a query (for instance field or table
    names).

    Example::

        >>> query = sql.SQL("select {} from {}").format(
        ...    sql.SQL(', ').join([sql.Identifier('foo'), sql.Identifier('bar')]),
        ...    sql.Identifier('table'))
        >>> print(query.as_string(conn))
        select "foo", "bar" from "table"

    .. automethod:: format

    .. automethod:: join
    """
    def __init__(self, string):
        if not isinstance(string, basestring):
            raise TypeError("SQL values must be strings")
        self._wrapped = string

    def __repr__(self):
        return "sql.SQL(%r)" % (self._wrapped,)

    def as_string(self, conn_or_curs):
        return self._wrapped

    def format(self, *args, **kwargs):
        """
        Merge `Composable` objects into a template.

        :param `Composable` args: parameters to replace to numbered
            (``{0}``, ``{1}``) or auto-numbered (``{}``) placeholders
        :param `Composable` kwargs: parameters to replace to named (``{name}``)
            placeholders
        :return: the union of the `!SQL` string with placeholders replaced
        :rtype: `Composed`

        The method is similar to the Python `str.format()` method: the string
        template supports auto-numbered (``{}``), numbered (``{0}``,
        ``{1}``...), and named placeholders (``{name}``), with positional
        arguments replacing the numbered placeholders and keywords replacing
        the named ones. However placeholder modifiers (``{{0!r}}``,
        ``{{0:<10}}``) are not supported. Only `!Composable` objects can be
        passed to the template.

        Example::

            >>> print(sql.SQL("select * from {} where {} = %s")
            ...     .format(sql.Identifier('people'), sql.Identifier('id'))
            ...     .as_string(conn))
            select * from "people" where "id" = %s

            >>> print(sql.SQL("select * from {tbl} where {pkey} = %s")
            ...     .format(tbl=sql.Identifier('people'), pkey=sql.Identifier('id'))
            ...     .as_string(conn))
            select * from "people" where "id" = %s

        """
        rv = []
        autonum = 0
        for pre, name, spec, conv in _formatter.parse(self._wrapped):
            if spec:
                raise ValueError("no format specification supported by SQL")
            if conv:
                raise ValueError("no format conversion supported by SQL")
            if pre:
                rv.append(SQL(pre))

            if name is None:
                continue

            if name.isdigit():
                if autonum:
                    raise ValueError(
                        "cannot switch from automatic field numbering to manual")
                rv.append(args[int(name)])
                autonum = None

            elif not name:
                if autonum is None:
                    raise ValueError(
                        "cannot switch from manual field numbering to automatic")
                rv.append(args[autonum])
                autonum += 1

            else:
                rv.append(kwargs[name])

        return Composed(rv)

    def join(self, seq):
        """
        Join a sequence of `Composable` or a `Composed` and return a `!Composed`.

        Use the object *string* to separate the *seq* elements.

        Example::

            >>> snip = sql.SQL(', ').join(
            ...     sql.Identifier(n) for n in ['foo', 'bar', 'baz'])
            >>> print(snip.as_string(conn))
            "foo", "bar", "baz"
        """
        if isinstance(seq, Composed):
            seq = seq._seq

        rv = []
        it = iter(seq)
        try:
            rv.append(it.next())
        except StopIteration:
            pass
        else:
            for i in it:
                rv.append(self)
                rv.append(i)

        return Composed(rv)


class Identifier(Composable):
    """
    A `Composable` representing an SQL identifer.

    Identifiers usually represent names of database objects, such as tables
    or fields. They follow `different rules`__ than SQL string literals for
    escaping (e.g. they use double quotes).

    .. __: https://www.postgresql.org/docs/current/static/sql-syntax-lexical.html# \
        SQL-SYNTAX-IDENTIFIERS

    Example::

        >>> t1 = sql.Identifier("foo")
        >>> t2 = sql.Identifier("ba'r")
        >>> t3 = sql.Identifier('ba"z')
        >>> print(sql.SQL(', ').join([t1, t2, t3]).as_string(conn))
        "foo", "ba'r", "ba""z"

    """
    def __init__(self, string):
        if not isinstance(string, basestring):
            raise TypeError("SQL identifiers must be strings")

        self._wrapped = string

    def __repr__(self):
        return "sql.Identifier(%r)" % (self._wrapped,)

    def as_string(self, conn_or_curs):
        return ext.quote_ident(self._wrapped, conn_or_curs)


class Literal(Composable):
    """
    A `Composable` representing an SQL value to include in a query.

    Usually you will want to include placeholders in the query and pass values
    as `~cursor.execute()` arguments. If however you really really need to
    include a literal value in the query you can use this object.

    The string returned by `!as_string()` follows the normal :ref:`adaptation
    rules <python-types-adaptation>` for Python objects.

    Example::

        >>> s1 = sql.Literal("foo")
        >>> s2 = sql.Literal("ba'r")
        >>> s3 = sql.Literal(42)
        >>> print(sql.SQL(', ').join([s1, s2, s3]).as_string(conn))
        'foo', 'ba''r', 42

    """
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __repr__(self):
        return "sql.Literal(%r)" % (self._wrapped,)

    def as_string(self, conn_or_curs):
        # is it a connection or cursor?
        if isinstance(conn_or_curs, ext.connection):
            conn = conn_or_curs
        elif isinstance(conn_or_curs, ext.cursor):
            conn = conn_or_curs.connection
        else:
            raise TypeError("conn_or_curs must be a connection or a cursor")

        a = ext.adapt(self._wrapped)
        if hasattr(a, 'prepare'):
            a.prepare(conn)

        rv = a.getquoted()
        if sys.version_info[0] >= 3 and isinstance(rv, bytes):
            rv = rv.decode(ext.encodings[conn.encoding])

        return rv


class Placeholder(Composable):
    """A `Composable` representing a placeholder for query parameters.

    If the name is specified, generate a named placeholder (e.g. ``%(name)s``),
    otherwise generate a positional placeholder (e.g. ``%s``).

    The object is useful to generate SQL queries with a variable number of
    arguments.

    Examples::

        >>> names = ['foo', 'bar', 'baz']

        >>> q1 = sql.SQL("insert into table (%s) values (%s)") % [
        ...     sql.SQL(', ').join(map(sql.Identifier, names)),
        ...     sql.SQL(', ').join(sql.Placeholder() * 3)]
        >>> print(q1.as_string(conn))
        insert into table ("foo", "bar", "baz") values (%s, %s, %s)

        >>> q2 = sql.SQL("insert into table (%s) values (%s)") % [
        ...         sql.SQL(', ').join(map(sql.Identifier, names)),
        ...         sql.SQL(', ').join(map(sql.Placeholder, names))]
        >>> print(q2.as_string(conn))
        insert into table ("foo", "bar", "baz") values (%(foo)s, %(bar)s, %(baz)s)

    """

    def __init__(self, name=None):
        if isinstance(name, basestring):
            if ')' in name:
                raise ValueError("invalid name: %r" % name)

        elif name is not None:
            raise TypeError("expected string or None as name, got %r" % name)

        self._name = name

    def __repr__(self):
        return "sql.Placeholder(%r)" % (
            self._name if self._name is not None else '',)

    def as_string(self, conn_or_curs):
        if self._name is not None:
            return "%%(%s)s" % self._name
        else:
            return "%s"


# Alias
PH = Placeholder

# Literals
NULL = SQL("NULL")
DEFAULT = SQL("DEFAULT")
