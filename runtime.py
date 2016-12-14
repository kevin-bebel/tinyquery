"""Implementation of the standard built-in functions."""
import abc
import datetime
import random
import time
import math
import re

import arrow

import compiler
import context
import tq_types
import tq_modes


class Function(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def check_types(self, *arg_types):
        """Return the type of the result as a function of the arg types.

        Raises a SyntaxError if the types are disallowed.
        """

    @abc.abstractmethod
    def evaluate(self, num_rows, *arg_lists):
        """Evaluates the function on

        Arguments:
            num_rows: The number of rows that should be returned. This is used
                by zero-arg functions that can't infer the number of rows from
                the args themselves.
            arg_lists: Each argument is a list of values for the column to
                operate on. For normal functions, the length of each arugment
                must be num_rows, but for aggregate functions, num_rows will be
                1 and each arg can be any length.
        """


class ArithmeticOperator(Function):
    """Basic operators like +."""
    def __init__(self, func):
        self.func = func

    def check_types(self, type1, type2):
        numeric_types = (tq_types.FLOAT, tq_types.INT)
        if type1 not in numeric_types or type2 not in numeric_types:
            raise TypeError('Expected int or float type')
        if type1 == tq_types.FLOAT or type2 == tq_types.FLOAT:
            return tq_types.FLOAT
        else:
            return tq_types.INT

    def evaluate(self, num_rows, column1, column2):
        values = [self.func(arg1, arg2) for arg1, arg2 in zip(column1.values,
                                                              column2.values)]
        # TODO(Samantha): Code smell incoming
        t = self.check_types(column1.type, column2.type)
        return context.Column(type=t, mode=tq_modes.NULLABLE, values=values)


class ComparisonOperator(Function):
    def __init__(self, func):
        self.func = func

    def check_types(self, type1, type2):
        # TODO: Fail if types are wrong.
        return tq_types.BOOL

    def evaluate(self, num_rows, column1, column2):
        values = [self.func(arg1, arg2) for arg1, arg2 in zip(column1.values,
                                                              column2.values)]
        return context.Column(type=tq_types.BOOL, mode=tq_modes.NULLABLE,
                              values=values)


class BooleanOperator(Function):
    def __init__(self, func):
        self.func = func

    def check_types(self, type1, type2):
        # TODO: Fail if types are wrong.
        return tq_types.BOOL

    def evaluate(self, num_rows, column1, column2):
        values = [self.func(arg1, arg2) for arg1, arg2 in zip(column1.values,
                                                              column2.values)]
        return context.Column(type=tq_types.BOOL, mode=tq_modes.NULLABLE,
                              values=values)


class UnaryIntOperator(Function):
    def __init__(self, func):
        self.func = func

    def check_types(self, arg):
        if arg != tq_types.INT:
            raise TypeError('Expected int type')
        return tq_types.INT

    def evaluate(self, num_rows, column):
        values = [self.func(arg) for arg in column.values]
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=values)


class UnaryBoolOperator(Function):
    def __init__(self, func):
        self.func = func

    def check_types(self, arg):
        return tq_types.BOOL

    def evaluate(self, num_rows, column):
        values = [self.func(arg) for arg in column.values]
        return context.Column(type=tq_types.BOOL, mode=tq_modes.NULLABLE,
                              values=values)


class IfFunction(Function):
    def check_types(self, cond, arg1, arg2):
        if cond != tq_types.BOOL:
            raise TypeError('Expected bool type.')
        if arg1 == tq_types.NONETYPE:
            return arg2
        if arg2 == tq_types.NONETYPE:
            return arg1
        if arg1 != arg2:
            raise TypeError('Expected types to be the same.')
        return arg1

    def evaluate(self, num_rows, condition_column, then_column, else_column):
        values = [arg1 if cond else arg2
                  for cond, arg1, arg2 in zip(condition_column.values,
                                              then_column.values,
                                              else_column.values)]
        t = self.check_types(condition_column.type, then_column.type,
                             else_column.type)
        return context.Column(type=t, mode=tq_modes.NULLABLE, values=values)


class IfNullFunction(Function):
    def check_types(self, arg1, arg2):
        if arg1 == tq_types.NONETYPE:
            return arg2
        if arg2 == tq_types.NONETYPE:
            return arg1
        if arg1 != arg2:
            raise TypeError('Expected types to be the same.')
        return arg1

    def evaluate(self, num_rows, arg1, arg2):
        return arg2 if arg1 is None else arg1


class HashFunction(Function):
    def check_types(self, arg):
        return tq_types.INT

    def evaluate(self, num_rows, column):
        # TODO: Use CityHash.
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=[hash(arg) for arg in column.values])


class FloorFunction(Function):
    def check_types(self, arg):
        if arg not in (tq_types.INT, tq_types.FLOAT):
            raise TypeError('Expected type int or float.')
        return tq_types.FLOAT

    def evaluate(self, num_rows, column):
        values = [math.floor(arg) for arg in column.values]
        return context.Column(type=tq_types.FLOAT, mode=tq_modes.NULLABLE,
                              values=values)


class RandFunction(Function):
    def check_types(self):
        return tq_types.FLOAT

    def evaluate(self, num_rows):
        values = [random.random() for _ in xrange(num_rows)]
        # TODO(Samantha): Should this be required?
        return context.Column(type=tq_types.FLOAT, mode=tq_modes.NULLABLE,
                              values=values)


def _check_regexp_types(*types):
    if any(t != tq_types.STRING for t in types):
        raise TypeError('Expected string arguments.')


def _ensure_literal(regexps):
    assert all(r == regexps[0] for r in regexps), "Must provide a literal."
    return regexps[0]


# TODO(colin): the regexp functions here use the python re module, while
# bigquery uses the re2 library, which only has a subset of the functionality.
# Investigate pulling in re2 here.

class RegexpMatchFunction(Function):
    def check_types(self, type1, type2):
        _check_regexp_types(type1, type2)
        return tq_types.BOOL

    def evaluate(self, num_rows, strings, regexps):
        regexp = _ensure_literal(regexps.values)
        values = (
            [True if re.search(regexp, s) else False for s in strings.values])
        return context.Column(type=tq_types.BOOL, mode=tq_modes.NULLABLE,
                              values=values)


class RegexpExtractFunction(Function):
    def check_types(self, type1, type2):
        _check_regexp_types(type1, type2)
        return tq_types.STRING

    def evaluate(self, num_rows, strings, regexps):
        regexp = _ensure_literal(regexps.values)
        values = []
        for s in strings.values:
            match_result = re.search(regexp, s)
            if match_result is None:
                values.append(None)
            else:
                assert len(match_result.groups()) == 1, (
                    "Exactly one capturing group required")
                values.append(match_result.group(1))
        return context.Column(type=tq_types.STRING, mode=tq_modes.NULLABLE,
                              values=values)


class RegexpReplaceFunction(Function):
    def check_types(self, re_type, str_type, repl_type):
        _check_regexp_types(re_type, str_type, repl_type)
        return tq_types.STRING

    def evaluate(self, num_rows, strings, regexps, replacements):
        regexp = _ensure_literal(regexps.values)
        replacement = _ensure_literal(replacements.values)
        values = [re.sub(regexp, replacement, s) for s in strings.values]
        return context.Column(type=tq_types.STRING, mode=tq_modes.NULLABLE,
                              values=values)


# TODO(Samantha): I'm not sure how this actually works, leaving for now.
class NthFunction(Function):
    # TODO(alan): Enforce that NTH takes a constant as its first arg.
    def check_types(self, index_type, rep_list_type):
        if index_type != tq_types.INT:
            raise SyntaxError('Expected an int index.')
        # TODO(alan): Add a list type instead of assuming ints.
        return tq_types.INT

    def evaluate(self, num_rows, index_list, column):
        # Ideally, this would take a constant and not a full expression, but to
        # hack around it for now, we'll just take the value at the first "row",
        # which works if the expression was a constant.
        index = index_list.values[0]
        values = [self.safe_index(rep_elem, index)
                  for rep_elem in column.values]
        # TODO(Samantha): This is almost certainly incorrect.
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=values)

    @staticmethod
    def safe_index(rep_elem, index):
        if not rep_elem:
            return None
        if index <= 0 or index > len(rep_elem):
            return None
        return rep_elem[index - 1]


class FirstFunction(Function):
    def check_types(self, rep_list_type):
        return rep_list_type

    def evaluate(self, num_rows, column):
        values = []
        if len(column.values) == 0:
            values = [None]

        if column.mode == tq_modes.REPEATED:
            values = [repeated_row[0] if len(repeated_row) > 0 else None
                      for repeated_row in column.values]
        else:
            values = [column.values[0]]
        return context.Column(type=column.type, mode=tq_modes.NULLABLE,
                              values=values)


class NoArgFunction(Function):
    def __init__(self, func, return_type=tq_types.INT):
        self.func = func
        self.type = return_type

    def check_types(self):
        return self.type

    def evaluate(self, num_rows):
        return context.Column(type=self.type, mode=tq_modes.NULLABLE,
                              values=[self.func() for _ in xrange(num_rows)])


class InFunction(Function):
    def check_types(self, arg1, *arg_types):
        return tq_types.BOOL

    def evaluate(self, num_rows, arg1, *other_args):
        values = [val1 in val_list
                  for val1, val_list in zip(arg1.values,
                                            zip(*(map(lambda x: x.values,
                                                      other_args))))]
        return context.Column(type=tq_types.BOOL, mode=tq_modes.NULLABLE,
                              values=values)


class ConcatFunction(Function):
    def check_types(self, *arg_types):
        if any(arg_type != tq_types.STRING for arg_type in arg_types):
            raise TypeError('CONCAT only takes string arguments.')
        return tq_types.STRING

    def evaluate(self, num_rows, *columns):
        values = [''.join(strs) for strs in zip(*map(lambda x: x.values,
                                                     columns))]
        return context.Column(tq_types.STRING, tq_modes.NULLABLE,
                              values=values)


class StringFunction(Function):
    def check_types(self, arg_type):
        return tq_types.STRING

    def evaluate(self, num_rows, column):
        values = [str(arg) for arg in column.values]
        return context.Column(type=tq_types.STRING, mode=tq_modes.NULLABLE,
                              values=values)


class MinMaxFunction(Function):
    def __init__(self, func):
        self.func = func

    def check_types(self, arg):
        return arg

    def evaluate(self, num_rows, column):
        return context.Column(type=self.check_types(column.type),
                              mode=tq_modes.NULLABLE,
                              values=[self.func(column.values)])


class SumFunction(Function):
    def check_types(self, arg):
        if arg == tq_types.BOOL:
            return tq_types.INT
        elif arg == tq_types.INT or arg == tq_types.FLOAT:
            return arg
        else:
            raise TypeError('Unexpected type.')

    def evaluate(self, num_rows, column):
        values = [sum([0 if arg is None else arg for arg in column.values])]
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=values)


class CountFunction(Function):
    def check_types(self, arg):
        return tq_types.INT

    def evaluate(self, num_rows, column):
        values = [len([0 for arg in column.values if arg is not None])]
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=values)


class AvgFunction(Function):
    def check_types(self, arg):
        return tq_types.FLOAT

    def evaluate(self, num_rows, column):
        filtered_args = [arg for arg in column.values if arg is not None]
        values = ([None] if not filtered_args else
                  [float(sum(filtered_args)) / len(filtered_args)])
        return context.Column(type=tq_types.FLOAT, mode=tq_modes.NULLABLE,
                              values=values)


class CountDistinctFunction(Function):
    def check_types(self, arg):
        return tq_types.INT

    def evaluate(self, num_rows, column):
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=[len(set(column.values))])


class StddevSampFunction(Function):
    def check_types(self, arg):
        return tq_types.FLOAT

    def evaluate(self, num_rows, column):
        # TODO(alan): Implement instead of returning 0.
        return context.Column(type=tq_types.FLOAT, mode=tq_modes.NULLABLE,
                              values=[0.0])


class QuantilesFunction(Function):
    # TODO(alan): Enforce that QUANTILES takes a constant as its second arg.
    def check_types(self, arg_list_type, num_quantiles_type):
        if num_quantiles_type != tq_types.INT:
            raise SyntaxError('Expected an int number of quantiles.')
        # TODO(alan): This should actually return a repeated version of the arg
        # list type.
        return tq_types.INT

    def evaluate(self, num_rows, column, num_quantiles_list):
        sorted_args = sorted(arg for arg in column.values if arg is not None)
        values = []
        if not sorted_args:
            values = [None]
        # QUANTILES is special because it takes a constant, not an expression
        # that gets repeated for each column. To hack around this for now, just
        # take the first element off.
        num_quantiles = num_quantiles_list.values[0]
        # Stretch the quantiles out so the first is always the min of the list
        # and the last is always the max of the list, but make sure it stays
        # within the bounds of the list so we don't get an IndexError.
        # This returns a single repeated field rather than one row per
        # quantile, so we need one more set of brackets than you might expect.
        values = [[
            sorted_args[
                min(len(sorted_args) * i / (num_quantiles - 1),
                    len(sorted_args) - 1)
            ] for i in xrange(num_quantiles)
        ]]
        return context.Column(type=tq_types.INT, mode=tq_modes.REPEATED,
                              values=values)


class ContainsFunction(Function):
    def check_types(self, type1, type2):
        if type1 != tq_types.STRING or type2 != tq_types.STRING:
            raise TypeError("CONTAINS must operate on strings.")
        return tq_types.BOOL

    def evaluate(self, num_rows, column1, column2):
        if len(column1.values) == len(column2.values):
            values = (
                [v2 in v1 for v1, v2 in zip(column1.values, column2.values)])
            return context.Column(type=tq_types.BOOL, mode=tq_modes.NULLABLE,
                                  values=values)


class TimestampFunction(Function):
    def check_types(self, type1):
        if type1 not in (tq_types.STRING, tq_types.INT, tq_types.TIMESTAMP):
            raise TypeError(
                'TIMESTAMP requires an ISO8601 string or unix timestamp in '
                'microseconds (or something that is already a timestamp).')
        return tq_types.TIMESTAMP

    def evaluate(self, num_rows, column):
        if column.type == tq_types.TIMESTAMP:
            return column

        converter = lambda ts: ts
        if num_rows > 0 and column.type == tq_types.INT:
            # Bigquery accepts integer number of microseconds since the unix
            # epoch here, whereas arrow wants a unix timestamp, with possible
            # decimal part representing microseconds.
            converter = lambda ts: float(ts) / 1E6
        values = [
            # arrow.get parses ISO8601 strings and int/float unix timestamps
            # without a format parameter
            arrow.get(converter(ts)).to('UTC').naive
            for ts in column.values
        ]
        return context.Column(type=tq_types.TIMESTAMP, mode=tq_modes.NULLABLE,
                              values=values)


class TimestampExtractFunction(Function):
    def __init__(self, extractor, return_type):
        self.extractor = extractor
        self.type = return_type

    def check_types(self, type1):
        if type1 != tq_types.TIMESTAMP:
            raise TypeError('Expected a timestamp, got %s.' % type1)
        return self.type

    def evaluate(self, num_rows, column1):
        values = map(self.extractor, column1.values)
        return context.Column(type=self.type, mode=tq_modes.NULLABLE,
                              values=values)


class DateAddFunction(Function):
    VALID_INTERVALS = ('YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND')

    def check_types(self, type1, type2, type3):
        if not (type1 == tq_types.TIMESTAMP and
                type2 == tq_types.INT and
                type3 == tq_types.STRING):
            raise TypeError(
                'DATE_ADD takes a timestamp, integer, and string specifying '
                'the interval. Got: (%s, %s, %s)' % (type1, type2, type3))

        return tq_types.TIMESTAMP

    def evaluate(self, num_rows, timestamps, nums_intervals, interval_types):
        num_intervals = _ensure_literal(nums_intervals.values)
        interval_type = _ensure_literal(interval_types.values)
        if interval_type not in self.VALID_INTERVALS:
            raise ValueError(
                'Valid values for the DATE_ADD interval are: %s.  Got %s.' % (
                    ', '.join(self.VALID_INTERVALS), interval_type))

        if interval_type == 'MONTH':
            def adder(ts):
                year = ts.year + (ts.month - 1 + num_intervals) // 12
                month = 1 + (ts.month - 1 + num_intervals) % 12
                return ts.replace(year=year, month=month)
            values = map(adder, timestamps.values)
        elif interval_type == 'YEAR':
            values = [ts.replace(year=(ts.year + num_intervals))
                      for ts in timestamps.values]
        else:
            # All of the other valid options for bigquery are also valid
            # keyword arguments to datetime.timedelta, when lowercased and
            # pluralized.
            python_interval_name = interval_type.lower() + 's'
            values = [
                ts + datetime.timedelta(
                    **{python_interval_name: num_intervals})
                for ts in timestamps.values]

        return context.Column(type=tq_types.TIMESTAMP, mode=tq_modes.NULLABLE,
                              values=values)


class DateDiffFunction(Function):
    def check_types(self, type1, type2):
        if not (type1 == tq_types.TIMESTAMP and type2 == tq_types.TIMESTAMP):
            raise TypeError('DATEDIFF requires two timestamps.')

        return tq_types.INT

    def evaluate(self, num_rows, lhs_ts, rhs_ts):
        values = [int(round((lhs - rhs).total_seconds() / 24 / 3600))
                  for lhs, rhs in zip(lhs_ts.values, rhs_ts.values)]
        return context.Column(type=tq_types.INT, mode=tq_modes.NULLABLE,
                              values=values)


class Compose(Function):
    """Function implementing function composition.

    Note that this is not actually a bigquery function, but a tool for
    combining them in implementations.
    """
    def __init__(self, *functions):
        self.functions = list(reversed(functions))
        assert len(self.functions) > 1, (
            'Compose requires at least two functions.')

    def check_types(self, *types):
        result = self.functions[0].check_types(*types)
        for f in self.functions[1:]:
            result = f.check_types(result)

        return result

    def evaluate(self, num_rows, *args):
        result = self.functions[0].evaluate(num_rows, *args)
        for f in self.functions[1:]:
            result = f.evaluate(num_rows, result)
        return result


class TimestampShiftFunction(Function):
    """Shift a timestamp to the beginning of the specified interval."""
    def __init__(self, interval):
        self.interval = interval
        assert interval in ('day', 'hour', 'month', 'year')

    def check_types(self, type1):
        if type1 != tq_types.TIMESTAMP:
            raise TypeError("Expected a timestamp.")
        return tq_types.TIMESTAMP

    def _hour_truncate(self, ts):
        return ts.replace(minute=0, second=0, microsecond=0)

    def _day_truncate(self, ts):
        return self._hour_truncate(ts).replace(hour=0)

    def _month_truncate(self, ts):
        return self._day_truncate(ts).replace(day=1)

    def _year_truncate(self, ts):
        return self._month_truncate(ts).replace(month=1)

    def evaluate(self, num_rows, timestamps):
        truncate_fn = getattr(self, '_%s_truncate' % self.interval)
        values = map(truncate_fn, timestamps.values)
        return context.Column(type=tq_types.TIMESTAMP, mode=tq_modes.NULLABLE,
                              values=values)


class UnixTimestampToWeekdayFunction(Function):
    """Shift a timestamp to the beginning of the specified day in the week.

    Note that in contrast to other day of week functions, days run from
    0 == Sunday to 6 == Saturday (for consistency with bigquery).
    """
    def check_types(self, type1, type2):
        if not (type1 == tq_types.INT and type2 == tq_types.INT):
            raise TypeError(
                'Expected a unix (integer) timestamp and an integer, '
                'got %s.' % [type1, type2])
        return tq_types.TIMESTAMP

    def _weekday_from_ts(self, ts):
        # isoweekday goes from 1 == Monday to 7 == Sunday
        return ts.isoweekday() % 7

    def evaluate(self, num_rows, unix_timestamps, weekdays):
        weekday = _ensure_literal(weekdays.values)
        timestamps = TimestampFunction().evaluate(num_rows, unix_timestamps)
        truncated = TimestampShiftFunction('day').evaluate(
            num_rows, timestamps)
        values = [
            ts + datetime.timedelta(
                days=(weekday - self._weekday_from_ts(ts)))
            for ts in truncated.values]
        ts_result = context.Column(
            type=tq_types.TIMESTAMP, mode=tq_modes.NULLABLE, values=values)
        return timestamp_to_usec.evaluate(num_rows, ts_result)


class StrftimeFunction(Function):
    """Format a unix timestamp in microseconds by the supplied format.

    TODO(colin): it appears that bigquery and python strftime behave
    identically.  Are there any differences?
    """
    def check_types(self, type1, type2):
        if not (type1 == tq_types.INT and type2 == tq_types.STRING):
            raise TypeError('Expected an integer and a string, got %s.' % (
                [type1, type2]))
        return tq_types.STRING

    def evaluate(self, num_rows, unix_timestamps, formats):
        format_str = _ensure_literal(formats.values)
        timestamps = TimestampFunction().evaluate(num_rows, unix_timestamps)
        values = [ts.strftime(format_str) for ts in timestamps.values]
        return context.Column(type=tq_types.STRING, mode=tq_modes.NULLABLE,
                              values=values)


timestamp_to_usec = TimestampExtractFunction(
    lambda dt: int(1E6 * arrow.get(dt).float_timestamp),
    return_type=tq_types.INT)


_UNARY_OPERATORS = {
    '-': UnaryIntOperator(lambda a: -a),
    'is_null': UnaryBoolOperator(lambda a: a is None),
    'is_not_null': UnaryBoolOperator(lambda a: a is not None),
}


_BINARY_OPERATORS = {
    '+': ArithmeticOperator(lambda a, b: a + b),
    '-': ArithmeticOperator(lambda a, b: a - b),
    '*': ArithmeticOperator(lambda a, b: a * b),
    '/': ArithmeticOperator(lambda a, b: a / b),
    '%': ArithmeticOperator(lambda a, b: a % b),
    '=': ComparisonOperator(lambda a, b: a == b),
    '!=': ComparisonOperator(lambda a, b: a != b),
    '>': ComparisonOperator(lambda a, b: a > b),
    '<': ComparisonOperator(lambda a, b: a < b),
    '>=': ComparisonOperator(lambda a, b: a >= b),
    '<=': ComparisonOperator(lambda a, b: a <= b),
    'and': BooleanOperator(lambda a, b: a and b),
    'or': BooleanOperator(lambda a, b: a or b),
    'contains': ContainsFunction(),
}


_FUNCTIONS = {
    'abs': UnaryIntOperator(abs),
    'floor': FloorFunction(),
    'rand': RandFunction(),
    'nth': NthFunction(),
    'concat': ConcatFunction(),
    'string': StringFunction(),
    'pow': ArithmeticOperator(lambda a, b: a ** b),
    'now': NoArgFunction(lambda: int(time.time() * 1000000)),
    'in': InFunction(),
    'if': IfFunction(),
    'ifnull': IfNullFunction(),
    'hash': HashFunction(),
    'regexp_match': RegexpMatchFunction(),
    'regexp_extract': RegexpExtractFunction(),
    'regexp_replace': RegexpReplaceFunction(),
    'timestamp': TimestampFunction(),
    'current_date': NoArgFunction(
        lambda: datetime.datetime.utcnow().strftime('%Y-%m-%d'),
        return_type=tq_types.STRING),
    'current_time': NoArgFunction(
        lambda: datetime.datetime.utcnow().strftime('%H:%M:%S'),
        return_type=tq_types.STRING),
    'current_timestamp': NoArgFunction(
        lambda: datetime.datetime.utcnow(),
        return_type=tq_types.TIMESTAMP),
    'date': Compose(
        TimestampExtractFunction(
            lambda dt: dt.strftime('%Y-%m-%d'),
            return_type=tq_types.STRING),
        TimestampFunction()),
    'date_add': DateAddFunction(),
    'datediff': DateDiffFunction(),
    'day': Compose(
        TimestampExtractFunction(
            lambda dt: dt.day,
            return_type=tq_types.INT),
        TimestampFunction()),
    'dayofweek': Compose(
        TimestampExtractFunction(
            # isoweekday uses Sunday == 7, but it's 1 in bigquery, so we need
            # to convert.
            lambda dt: (dt.isoweekday() % 7 + 1),
            return_type=tq_types.INT),
        TimestampFunction()),
    'dayofyear': Compose(
        TimestampExtractFunction(
            lambda dt: int(dt.strftime('%j'), 10),
            return_type=tq_types.INT),
        TimestampFunction()),
    'format_utc_usec': Compose(
        TimestampExtractFunction(
            lambda dt: dt.strftime('%Y-%m-%d %H:%M:%S.%f'),
            return_type=tq_types.STRING),
        TimestampFunction()),
    'hour': Compose(
        TimestampExtractFunction(
            lambda dt: dt.hour,
            return_type=tq_types.INT),
        TimestampFunction()),
    'minute': Compose(
        TimestampExtractFunction(
            lambda dt: dt.minute,
            return_type=tq_types.INT),
        TimestampFunction()),
    'month': Compose(
        TimestampExtractFunction(
            lambda dt: dt.month,
            return_type=tq_types.INT),
        TimestampFunction()),
    'msec_to_timestamp': Compose(
        TimestampFunction(),
        UnaryIntOperator(lambda msec: msec * 1E3)),
    'parse_utc_usec': Compose(
        timestamp_to_usec,
        TimestampFunction()),
    'quarter': Compose(
        TimestampExtractFunction(
            lambda dt: dt.month // 3 + 1,
            return_type=tq_types.INT),
        TimestampFunction()),
    'second': Compose(
        TimestampExtractFunction(
            lambda dt: dt.second,
            return_type=tq_types.INT),
        TimestampFunction()),
    'sec_to_timestamp': Compose(
        TimestampFunction(),
        UnaryIntOperator(lambda sec: sec * 1E6)),
    'strftime_utc_usec': StrftimeFunction(),
    'time': Compose(
        TimestampExtractFunction(
            lambda dt: dt.strftime('%H:%M:%S'),
            return_type=tq_types.STRING),
        TimestampFunction()),
    'timestamp_to_msec': TimestampExtractFunction(
        lambda dt: int(round(1E3 * arrow.get(dt).float_timestamp)),
        return_type=tq_types.INT),
    'timestamp_to_sec': TimestampExtractFunction(
        lambda dt: arrow.get(dt).timestamp,
        return_type=tq_types.INT),
    'timestamp_to_usec': timestamp_to_usec,
    'usec_to_timestamp': TimestampFunction(),
    'utc_usec_to_day': Compose(
        timestamp_to_usec,
        TimestampShiftFunction('day'),
        TimestampFunction()),
    'utc_usec_to_hour': Compose(
        timestamp_to_usec,
        TimestampShiftFunction('hour'),
        TimestampFunction()),
    'utc_usec_to_month': Compose(
        timestamp_to_usec,
        TimestampShiftFunction('month'),
        TimestampFunction()),
    'utc_usec_to_week': UnixTimestampToWeekdayFunction(),
    'utc_usec_to_year': Compose(
        timestamp_to_usec,
        TimestampShiftFunction('year'),
        TimestampFunction()),
    'week': Compose(
        TimestampExtractFunction(
            # TODO(colin): can this ever be 54?
            # Bigquery returns 1...53 inclusive
            # Python returns 0...53 inclusive
            # Both say that the first week may be < 7 days, but python calls
            # that 0, and bigquery calls that 1.
            lambda dt: int(dt.strftime('%U'), 10) + 1,
            return_type=tq_types.INT),
        TimestampFunction()),
    'year': Compose(
        TimestampExtractFunction(
            lambda dt: dt.year,
            return_type=tq_types.INT),
        TimestampFunction()),
}


_AGGREGATE_FUNCTIONS = {
    'sum': SumFunction(),
    'min': MinMaxFunction(min),
    'max': MinMaxFunction(max),
    'count': CountFunction(),
    'avg': AvgFunction(),
    'count_distinct': CountDistinctFunction(),
    'stddev_samp': StddevSampFunction(),
    'quantiles': QuantilesFunction(),
    'first': FirstFunction()
}


def get_unary_op(name):
    result = _UNARY_OPERATORS[name]
    assert isinstance(result, Function)
    return result


def get_binary_op(name):
    result = _BINARY_OPERATORS[name]
    assert isinstance(result, Function)
    return result


def get_func(name):
    if name in _FUNCTIONS:
        return _FUNCTIONS[name]
    elif name in _AGGREGATE_FUNCTIONS:
        return _AGGREGATE_FUNCTIONS[name]
    else:
        raise compiler.CompileError('Unknown function: {}'.format(name))


def is_aggregate_func(name):
    return name in _AGGREGATE_FUNCTIONS
