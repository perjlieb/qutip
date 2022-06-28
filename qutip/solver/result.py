""" Class for solve function results"""
import numpy as np
from ..core import Qobj, QobjEvo, expect

__all__ = ["Result", "MultiTrajResult", "MultiTrajResultAveraged"]


class _QobjExpectEop:
    """
    Pickable e_ops callable that calculates the expectation value for a given
    operator.

    Parameters
    ----------
    op : :obj:`~Qobj`
        The expectation value operator.
    """
    def __init__(self, op):
        self.op = op

    def __call__(self, t, state):
        return expect(self.op, state)


class ExpectOp:
    """
    A result e_op (expectation operation).

    Parameters
    ----------
    op : object
        The original object used to define the e_op operation, e.g. a
        :~obj:`Qobj` or a function ``f(t, state)``.

    f : function
        A callable ``f(t, state)`` that will return the value of the e_op
        for the specified state and time.

    append : function
        A callable ``append(value)``, e.g. ``expect[k].append``, that will
        store the result of the e_ops function ``f(t, state)``.

    Attributes
    ----------
    op : object
        The original object used to define the e_op operation.
    """
    def __init__(self, op, f, append):
        self.op = op
        self._f = f
        self._append = append

    def __call__(self, t, state):
        """
        Return the expectation value for the given time, ``t`` and
        state, ``state``.
        """
        return self._f(t, state)

    def _store(self, t, state):
        """
        Store the result of the e_op function. Should only be called by
        :class:`~Result`.
        """
        self._append(self._f(t, state))


class Result:
    """
    Base class for storing solver results.

    Parameters
    ----------
    e_ops : :obj:`~Qobj`, :obj:`~QobjEvo`, function or list or dict of these
        The ``e_ops`` parameter defines the set of values to record at
        each time step ``t``. If an element is a :obj:`~Qobj` or
        :obj:`~QobjEvo` the value recorded is the expectation value of that
        operator given the state at ``t``. If the element is a function, ``f``,
        the value recorded is ``f(t, state)``.

        The values are recorded in the ``.expect`` attribute of this result
        object. ``.expect`` is a list, where each item contains the values
        of the corresponding ``e_op``.

    options : :obj:`~SolverOptions`
        The options for this result class.

    solver : str or None
        The name of the solver generating these results.

    stats : dict or None
        The stats generated by the solver while producing these results. Note
        that the solver may update the stats directly while producing results.

    kw : dict
        Additional parameters specific to a result sub-class.

    Attributes
    ----------
    times : list
        A list of the times at which the expectation values and states were
        recorded.

    states : list of :obj:`~Qobj`
        The state at each time ``t`` (if the recording of the state was
        requested).

    final_state : :obj:`~Qobj:
        The final state (if the recording of the final state was requested).

    expect : list of lists of expectation values
        A list containing the values of each ``e_op``. The list is in
        the same order in which the ``e_ops`` were supplied and empty if
        no ``e_ops`` were given.

        Each element is itself a list and contains the values of the
        corresponding ``e_op``, with one value for each time in ``.times``.

        The same lists of values may be accessed via the ``.e_data`` dictionary
        and the original ``e_ops`` are available via the ``.e_ops`` attribute.

    e_data : dict
        A dictionary containing the values of each ``e_op``. If the ``e_ops``
        were supplied as a dictionary, the keys are the same as in
        that dictionary. Otherwise the keys are the index of the ``e_op``
        in the ``.expect`` list.

        The lists of expectation values returned are the *same* lists as
        those returned by ``.expect``.

    e_ops : dict
        A dictionary containing the supplied e_ops as ``ExpectOp`` instances.
        The keys of the dictionary are the same as for ``.e_data``.
        Each value is object where ``.e_ops[k](t, state)`` calculates the
        value of ``e_op`` ``k`` at time ``t`` and the given ``state``, and
        ``.e_ops[k].op`` is the original object supplied to create the
        ``e_op``.

    solver : str or None
        The name of the solver generating these results.

    stats : dict or None
        The stats generated by the solver while producing these results.

    options : :obj:`~SolverOptions`
        The options for this result class.
    """
    def __init__(self, e_ops, options, *, solver=None, stats=None, **kw):
        self.solver = solver
        self.stats = stats

        self._state_processors = []
        self._state_processors_require_copy = False

        raw_ops = self._e_ops_to_dict(e_ops)
        self.e_data = {k: [] for k in raw_ops}
        self.expect = list(self.e_data.values())
        self.e_ops = {}
        for k, op in raw_ops.items():
            f = self._e_op_func(op)
            self.e_ops[k] = ExpectOp(op, f, self.e_data[k].append)
            self.add_processor(self.e_ops[k]._store)

        self.options = options

        self.times = []
        self.states = []
        self.final_state = None

        self._post_init(**kw)

    def _e_ops_to_dict(self, e_ops):
        """ Convert the supplied e_ops to a dictionary of Eop instances. """
        if e_ops is None:
            e_ops = {}
        elif isinstance(e_ops, (list, tuple)):
            e_ops = {k: e_op for k, e_op in enumerate(e_ops)}
        elif isinstance(e_ops, dict):
            pass
        else:
            e_ops = {0: e_ops}
        return e_ops

    def _e_op_func(self, e_op):
        """
        Convert an e_op entry into a function, ``f(t, state)`` that returns
        the appropriate value (usually an expectation value).

        Sub-classes may override this function to calculate expectation values
        in different ways.
        """
        if isinstance(e_op, Qobj):
            return _QobjExpectEop(e_op)
        elif isinstance(e_op, QobjEvo):
            return e_op.expect
        elif callable(e_op):
            return e_op
        raise TypeError(f"{e_op!r} has unsupported type {type(e_op)!r}.")

    def _post_init(self):
        """
        Perform post __init__ initialisation. In particular, add state
        processors or pre-processors.

        Sub-class may override this. If the sub-class wishes to register the
        default processors for storing states, it should call this parent
        ``.post_init()`` method.

        Sub-class ``.post_init()`` implementation may take additional keyword
        arguments if required.
        """
        store_states = self.options['store_states']
        store_final_state = self.options['store_final_state']

        if store_states is None:
            store_states = len(self.e_ops) == 0
        if store_states:
            self.add_processor(self._store_state, requires_copy=True)

        if store_states or store_final_state:
            self.add_processor(self._store_final_state, requires_copy=True)

    def _store_state(self, t, state):
        """ Processor that stores a state in ``.states``. """
        self.states.append(state)

    def _store_final_state(self, t, state):
        """ Processor that writes the state to ``.final_state``. """
        self.final_state = state

    def _pre_copy(self, state):
        """ Return a copy of the state. Sub-classes may override this to
            copy a state in different manner or to skip making a copy
            altogether if a copy is not necessary.
        """
        return state.copy()

    def add_processor(self, f, requires_copy=False):
        """
        Append a processor ``f`` to the list of state processors.

        Parameters
        ----------
        f : function, ``f(t, state)``
            A function to be called each time a state is added to this
            result object. The state is the state passed to ``.add``, after
            applying the pre-processors, if any.

        requires_copy : bool, default False
            Whether this processor requires a copy of the state rather than
            a reference. A processor must never modify the supplied state, but
            if a processor stores the state it should set ``require_copy`` to
            true.
        """
        self._state_processors.append(f)
        self._state_processors_require_copy |= requires_copy

    def add(self, t, state):
        """
        Add a state to the results for the time ``t`` of the evolution.

        Adding a state calculates the expectation value of the state for
        each of the supplied ``e_ops`` and stores the result in ``.expect``.

        The state is recorded in ``.states`` and ``.final_state`` if specified
        by the supplied result options.

        Parameters
        ----------
        t : float
            The time of the added state.

        state : typically a :obj:`~Qobj`
            The state a time ``t``. Usually this is a :obj:`~Qobj` with
            suitable dimensions, but it sub-classes of result might support
            other forms of the state.

        .. note::

           The expectation values, i.e. ``e_ops``, and states are recorded by
           the state processors (see ``.add_processor``).

           Additional processors may be added by sub-classes.
        """
        self.times.append(t)

        if self._state_processors_require_copy:
            state = self._pre_copy(state)

        for op in self._state_processors:
            op(t, state)

    def __repr__(self):
        lines = [
            f"<{self.__class__.__name__}",
            f"  Solver: {self.solver}",
        ]
        if self.stats:
            lines.append("  Solver stats:")
            lines.extend(
                f"    {k}: {v!r}"
                for k, v in self.stats.items()
            )
        if self.times:
            lines.append(
                f"  Time interval: [{self.times[0]}, {self.times[-1]}]"
                f" ({len(self.times)} steps)"
            )
        lines.append(f"  Number of e_ops: {len(self.e_ops)}")
        if self.states:
            lines.append("  States saved.")
        elif self.final_state is not None:
            lines.append("  Final state saved.")
        else:
            lines.append("  State not saved.")
        lines.append(">")
        return "\n".join(lines)


class MultiTrajResult:
    """
    Contain result of simulations with multiple trajectories. Keeps all
    trajectories' data.

    Property
    --------

    runs_states : list of list of Qobj
        Every state of the evolution for each trajectories. (ket)

    average_states : list of Qobj
        Average state for each time. (density matrix)

    runs_final_states : Qobj
        Average last state for each trajectories. (ket)

    average_final_state : Qobj
        Average last state. (density matrix)

    steady_state : Qobj
        Average state of each time and trajectories. (density matrix)

    runs_expect : list of list of list of number
        Expectation values for each [e_ops, trajectory, time]

    average_expect : list of list of number
        Averaged expectation values over trajectories.

    std_expect : list of list of number
        Standard derivation of each averaged expectation values.

    expect : list
        list of list of averaged expectation values.

    times : list
        list of the times at which the expectation values and
        states where taken.

    stats :
        Diverse statistics of the evolution.

    num_expect : int
        Number of expectation value operators in simulation.

    num_collapse : int
        Number of collapse operators in simualation.

    num_traj : int/list
        Number of trajectories (for stochastic solvers). A list indicates
        that averaging of expectation values was done over a subset of total
        number of trajectories.

    col_times : list
        Times at which state collpase occurred. Only for Monte Carlo solver.

    col_which : list
        Which collapse operator was responsible for each collapse in
        ``col_times``. Only for Monte Carlo solver.

    collapse : list
        Each collapse per trajectory as a (time, which_oper)

    photocurrent : list
        photocurrent corresponding to each collapse operator.

    Methods
    -------
    expect_traj_avg(ntraj):
        Averaged expectation values over `ntraj` trajectories.

    expect_traj_std(ntraj):
        Standard derivation of expectation values over `ntraj` trajectories.
        Last state of each trajectories. (ket)
    """
    def __init__(self, num_c_ops=0):
        """
        Parameters:
        -----------
        num_c_ops: int
            Number of collapses operator used in the McSolver
        """
        self.trajectories = []
        self._to_dm = True # MCsolve
        self.num_c_ops = num_c_ops
        self.tlist = None

    def add(self, one_traj):
        self.trajectories.append(one_traj)

    @property
    def runs_states(self):
        return [traj.states for traj in self.trajectories]

    @property
    def average_states(self):
        if self._to_dm:
            finals = [state.proj() for state in self.trajectories[0].states]
            for i in range(1, len(self.trajectories)):
                finals = [state.proj() + final for final, state
                          in zip(finals, self.trajectories[i].states)]
        else:
            finals = [state for state in self.trajectories[0].states]
            for i in range(1, len(self.trajectories)):
                finals = [state + final for final, state
                          in zip(finals, self.trajectories[i].states)]
        return [final / len(self.trajectories) for final in finals]

    @property
    def runs_final_states(self):
        return [traj.final_state for traj in self.trajectories]

    @property
    def average_final_state(self):
        if self._to_dm:
            final = sum(traj.final_state.proj() for traj in self.trajectories)
        else:
            final = sum(traj.final_state for traj in self.trajectories)
        return final / len(self.trajectories)

    @property
    def steady_state(self):
        avg = self.average_states
        return sum(avg) / len(avg)

    @property
    def average_expect(self):
        return {
            k: np.mean(np.stack([
                traj.expect[k] for traj in self.trajectories
            ]), axis=0)
            for k in self.trajectories[0].e_ops
        }

    @property
    def std_expect(self):
        return {
            k: np.std(np.stack([
                traj.expect[k] for traj in self.trajectories
            ]), axis=0)
            for k in self.trajectories[0].e_ops
        }

    @property
    def runs_expect(self):
        return {
            k: np.stack([
                traj.expect[k] for traj in self.trajectories
            ])
            for k in self.trajectories[0].e_ops
        }

    def expect_traj_avg(self, ntraj=-1):
        return {
            k: np.std(np.stack([
                traj.expect[k] for traj in self.trajectories[:ntraj]
            ]), axis=0)
            for k in self.trajectories[0].e_ops
        }

    def expect_traj_std(self, ntraj=-1):
        return {
            k: np.std(np.stack([
                traj.expect[k] for traj in self.trajectories[:ntraj]
            ]), axis=0)
            for k in self.trajectories[0].e_ops
        }

    @property
    def collapse(self):
        return [traj.collapse for traj in self.trajectories]

    @property
    def col_times(self):
        out = []
        for col_ in self.collapse:
            col = list(zip(*col_))
            col = ([] if len(col) == 0 else col[0])
            out.append(col)
        return out

    @property
    def col_which(self):
        out = []
        for col_ in self.collapse:
            col = list(zip(*col_))
            col = ([] if len(col) == 0 else col[1])
            out.append(col)
        return out

    @property
    def photocurrent(self):
        cols = {}
        tlist = self.trajectories[0].times
        for traj in self.trajectories:
            for t, which in traj.collapse:
                if which in cols:
                    cols[which].append(t)
                else:
                    cols[which] = [t]
        mesurement = []
        for i in range(self.num_c_ops):
            mesurement += [(np.histogram(cols.get(i,[]), tlist)[0]
                          / np.diff(tlist) / len(self.trajectories))]
        return mesurement

    @property
    def run_stats(self):
        return self.trajectories[0].stats

    def __repr__(self):
        out = ""
        out += self.run_stats['solver'] + "\n"
        out += "solver : " + self.stats['method'] + "\n"
        out += "{} runs saved\n".format(self.num_traj)
        out += "number of expect : {}\n".format(self.trajectories[0]._e_num)
        if self.trajectories[0]._store_states:
            out += "Runs states saved\n"
        elif self.trajectories[0]._store_final_state:
            out += "Runs final state saved\n"
        else:
            out += "State not available\n"
        out += "times from {} to {} in {} steps\n".format(self.times[0],
                                                          self.times[-1],
                                                          len(self.times))
        return out

    @property
    def times(self):
        return self.trajectories[0].times

    @property
    def states(self):
        return self.average_states

    @property
    def expect(self):
        return self.average_expect

    @property
    def final_state(self):
        return self.average_final_state

    @property
    def num_traj(self):
        return len(self.trajectories)

    @property
    def num_expect(self):
        return self.trajectories[0].num_expect

    @property
    def num_collapse(self):
        return self.trajectories[0].num_collapse


class MultiTrajResultAveraged:
    """
    Contain result of simulations with multiple trajectories.
    Only keeps the averages.

    Property
    --------
    average_states : list of Qobj
        Average state for each time. (density matrix)

    average_final_state : Qobj
        Average last state. (density matrix)

    steady_state : Qobj
        Average state of each time and trajectories. (density matrix)

    average_expect : list of list of number
        Averaged expectation values over trajectories.

    std_expect : list of list of number
        Standard derivation of each averaged expectation values.

    expect : list
        list of list of averaged expectation values.

    times : list
        list of the times at which the expectation values and
        states where taken.

    stats :
        Diverse statistics of the evolution.

    num_expect : int
        Number of expectation value operators in simulation.

    num_collapse : int
        Number of collapse operators in simualation.

    num_traj : int/list
        Number of trajectories (for stochastic solvers). A list indicates
        that averaging of expectation values was done over a subset of total
        number of trajectories.

    col_times : list
        Times at which state collpase occurred. Only for Monte Carlo solver.

    col_which : list
        Which collapse operator was responsible for each collapse in
        ``col_times``. Only for Monte Carlo solver.

    collapse : list
        Each collapse per trajectory as a (time, which_oper)

    photocurrent : list
        photocurrent corresponding to each collapse operator.

    """
    def __init__(self, num_c_ops=0):
        """
        Parameters:
        -----------
        num_c_ops: int
            Number of collapses operator used in the McSolver
        """
        self.trajectories = None
        self._sum_states = None
        self._sum_last_states = None
        self._sum_expect = None
        self._sum2_expect = None
        self._to_dm = True # MCsolve
        self.num_c_ops = num_c_ops
        self._num = 0
        self._collapse = []

    def add(self, one_traj):
        if self._num == 0:
            self.trajectories = one_traj
            if self._to_dm and one_traj.states:
                self._sum_states = [state.proj() for state in one_traj.states]
            else:
                self._sum_states = one_traj.states
            if self._to_dm and one_traj.final_state:
                self._sum_last_states = one_traj.final_state.proj()
            else:
                self._sum_last_states = one_traj.final_state
            self._sum_expect = [
                np.array(expect) for expect in one_traj.expect
            ]
            self._sum2_expect = [
                np.array(expect)**2 for expect in one_traj.expect
            ]
        else:
            if self._to_dm:
                if self._sum_states:
                    self._sum_states = [state.proj() + accu for accu, state
                                    in zip(self._sum_states, one_traj.states)]
                if self._sum_last_states:
                    self._sum_last_states += one_traj.final_state.proj()
            else:
                if self._sum_states:
                    self._sum_states = [state + accu for accu, state
                                    in zip(self._sum_states, one_traj.states)]
                if self._sum_last_states:
                    self._sum_last_states += one_traj.final_state
            if self._sum_expect:
                self._sum_expect = [
                    self._sum_expect[i] + np.array(one_traj.expect[i])
                    for i in range(len(self._sum_expect))
                ]
                self._sum2_expect = [
                    self._sum2_expect[i] + np.array(one_traj.expect[i])**2
                    for i in range(len(self._sum2_expect))
                ]
        self._collapse.append(one_traj.collapse)
        self._num += 1

    @property
    def runs_states(self):
        return None

    @property
    def average_states(self):
        return [final / self._num for final in self._sum_states]

    @property
    def runs_final_states(self):
        return None

    @property
    def average_final_state(self):
        return self._sum_last_states / self._num

    @property
    def steady_state(self):
        avg = self._sum_states
        return sum(avg) / len(avg)

    @property
    def average_expect(self):
        return [v / self._num for v in self._sum_expect]

    @property
    def std_expect(self):
        return [
            np.sqrt(
                self._sum2_expect[i] / self._num -
                (self._sum_expect[i] / self._num) ** 2
            )
            for i in range(len(self._sum_expect))
        ]

    @property
    def runs_expect(self):
        return None

    def expect_traj_avg(self, ntraj=-1):
        return None

    def expect_traj_std(self, ntraj=-1):
        return None

    @property
    def collapse(self):
        return self._collapse

    @property
    def col_times(self):
        out = []
        for col_ in self.collapse:
            col = list(zip(*col_))
            col = ([] if len(col) == 0 else col[0])
            out.append(col)
        return out

    @property
    def col_which(self):
        out = []
        for col_ in self.collapse:
            col = list(zip(*col_))
            col = ([] if len(col) == 0 else col[1])
            out.append(col)
        return out

    @property
    def photocurrent(self):
        cols = {}
        tlist = self.trajectories.times
        for collapses in self.collapse:
            for t, which in collapses:
                if which in cols:
                    cols[which].append(t)
                else:
                    cols[which] = [t]
        mesurement = []
        for i in range(self.num_c_ops):
            mesurement += [(np.histogram(cols.get(i,[]), tlist)[0]
                          / np.diff(tlist) / self._num)]
        return mesurement

    @property
    def run_stats(self):
        return self.trajectories.stats

    def __repr__(self):
        out = ""
        out += self.run_stats['solver'] + "\n"
        out += "solver : " + self.stats['method'] + "\n"
        out += "{} trajectories averaged\n".format(self.num_traj)
        out += "number of expect : {}\n".format(self.trajectories._e_num)
        if self.trajectories._store_states:
            out += "States saved\n"
        elif self.trajectories._store_final_state:
            out += "Final state saved\n"
        else:
            out += "State not available\n"
        out += "times from {} to {} in {} steps\n".format(self.times[0],
                                                          self.times[-1],
                                                          len(self.times))
        return out

    @property
    def times(self):
        return self.trajectories.times

    @property
    def states(self):
        return self.average_states

    @property
    def expect(self):
        return self.average_expect

    @property
    def final_state(self):
        return self.average_final_state

    @property
    def num_traj(self):
        return self._num

    @property
    def num_expect(self):
        return self.trajectories.num_expect

    @property
    def num_collapse(self):
        return self.trajectories.num_collapse
