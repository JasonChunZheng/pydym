""" file:   flow_data.py (pydym)
    author: Jess Robertson
            CSIRO Minerals Resources Flagship
    date:   Tuesday 24 June 2014

    description: Data structures for velocity fields
"""

from __future__ import division
import numpy
import h5py
import os
from itertools import product

from .utilities import thinned_length


class FlowDatum(object):

    """ A class to store velocity data from a flow visualisation
    """

    def __init__(self, xs, ys, us, vs, pressure, tracer):
        super(FlowDatum, self).__init__()
        self.position = numpy.vstack([xs, ys])
        self.velocity = numpy.vstack([us, vs])
        self.pressure = pressure
        self.tracer = tracer

        self._length = len(us)

    def __len__(self):
        return self._length


class FlowData(object):

    """ A class to store velocity data from a collection of flow visualisations
    """

    default_axis_labels = ('x', 'y', 'z')

    def __init__(self, filename, snapshot_keys=('velocity',),
                 n_snapshots=None, n_samples=None, n_dimensions=2,
                 vector_datasets=('position', 'velocity'),
                 scalar_datasets=('pressure', 'tracer'),
                 update=False):
        super(FlowData, self).__init__()
        self.n_samples, self.n_snapshots = n_samples, n_snapshots
        self.n_dimensions = n_dimensions
        self.filename = filename
        self.set_snapshot_datasets(snapshot_keys)
        self.vectors, self.scalars = vector_datasets, scalar_datasets

        # Determine shapes and labels
        self.shape = (self.n_samples, self.n_snapshots)
        self.axis_labels = \
            [self.default_axis_labels[i] for i in range(self.n_dimensions)]
        self._snapshots = None

        # Initialize file
        self._file = None
        if os.path.exists(filename) and not update:
            self._init_from_file()
        else:
            self._init_from_arguments()

    def _init_from_file(self):
        """ Initialize the FlowData object from an HDF5 resource
        """
        self._file = h5py.File(self.filename, 'a')
        self.shape = self['position/x'].shape
        self.n_dimensions = len(self['position'].keys())
        self.axis_labels = self['position'].keys()
        self.vectors = [n for n, v in self._file.items()
                        if type(v) is h5py.Group]
        self.scalars = [n for n, v in self._file.items()
                        if type(v) is h5py.Dataset]

    def _init_from_arguments(self):
        """ Initialize the FlowData object from the arguments given to __init__
        """
        # Check inputs to __init__ are specced
        if any((s is None for s in self.shape)):
            raise ValueError('You must specify a shape for a new FlowData '
                             'object created from scratch')

        # Create file - ensure any existing files are deleted (which may be the
        # case if update=True in __init__)
        if os.path.exists(self.filename):
            os.remove(self.filename)
        self._file = h5py.File(self.filename, 'w')

        # Map out vector datasets
        for dset_name in self.vectors:
            grp = self._file.create_group(dset_name)
            for dim_idx in range(self.n_dimensions):
                grp.require_dataset(name=self.axis_labels[dim_idx],
                                    shape=self.shape,
                                    dtype=float,
                                    compression="gzip")

        # Map out scalar datasets
        for dset_name in self.scalars:
            self._file.require_dataset(name=dset_name,
                                       shape=self.shape,
                                       dtype=float,
                                       compression="gzip")

    def __getitem__(self, value_or_key):
        """ Get the data associated with a given index or key

            If value_or_key is an integer index, return the FlowDatum object
            associated with that snapshot. If value_or_key is a string, return
            the h5py.Dataset object for that string.
        """
        if type(value_or_key) is int:
            # We have an index
            idx = value_or_key

            # Reconstruct FlowDatum
            return FlowDatum(
                xs=self['position/x'][idx], ys=self['position/y'][idx],
                us=self['velocity/x'][idx], vs=self['velocity/y'][idx],
                pressure=self['pressure'][idx],
                tracer=self['tracer'][idx])
        else:
            # We have a key
            return self._file[value_or_key]

    def __setitem__(self, idx, flow_datum):
        """ Set the snapshot data at the given index
        """
        if type(flow_datum) is not FlowDatum:
            raise ValueError("Trying to append non-FlowDatum object to "
                             "FlowData collection")

        # Append vector data in the right places
        for dset in self.vectors:
            values = getattr(flow_datum, dset)
            if values is not None:
                for aidx, axis in enumerate(self.axis_labels):
                    self._file[dset + '/' + axis][:, idx] = values[aidx]

        # Update scalar data
        for dset in self.scalars:
            values = getattr(flow_datum, dset)
            if values is not None:
                self._file[dset][:, idx] = values

        self._recalc_snapshots = True

    @property
    def snapshots(self):
        """ Returns the snapshot array for the data
        """
        if not self._snapshots:
            self.generate_snapshots()
        return self._snapshots

    def set_snapshot_datasets(self, snapshot_keys):
        """ Set the datasets used to generate snapshots
        """
        self.snapshot_keys = snapshot_keys
        self._snapshots = None

    def thin_snapshots(self, thin_by):
        """ Thin the snapshot sequence by taking only every nth snapshot

            :param thin_by: Take every 'thin_by' snapshots. `thin_by = None`
                removes thinning.
            :type thin_by: int or None
        """
        self.thin_by = thin_by
        self._snapshots = None

    def generate_snapshots(self):
        """ Generate the snapshots
        """
        # Make snapshot dataset
        dset_name = '_'.join(self.snapshot_keys)
        if self.thin_by:
            dset_name += '_thin_by_{0}'.format(self.thin_by)

        # Determine number of measurements per sample - need to include fact
        # that vector snapshots have more samples
        vector_components = [key + '/' + ax
                             for ax, key in product(self.axis_labels,
                                                    self.snapshot_keys)
                             if key in self.vectors]
        scalar_components = [key for key in self.snapshot_keys
                             if key not in self.vectors]
        all_components = tuple(vector_components + scalar_components)
        n_components = len(all_components)

        # Determine snapshot size
        if self.thin_by:
            snapshot_size = (n_components * self.n_samples,
                             thinned_length(self.n_snapshots, self.thin_by))
        else:
            snapshot_size = (n_components * self.n_samples, self.n_snapshots)

        # Generate group for snapshots
        snapshot_grp = self._file.require_group('snapshots')
        self._snapshots = snapshot_grp.require_dataset(
            name=dset_name, shape=snapshot_size,
            dtype=float, compression="gzip")
        self._snapshots.attrs['keys'] = all_components

        # Copy over dataset data
        for idx, key in enumerate(all_components):
            if self.thin_by:
                self._snapshots[idx::n_components] = \
                    self[key][:, ::self.thin_by]
            else:
                self._snapshots[idx::n_components] = self[key]
