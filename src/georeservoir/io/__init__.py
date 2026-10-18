"""Data ingestion with file provenance and validation reports (Phase 2).

Readers here are **outside** the numerical core: they may depend on optional third-party
parsers (install with ``pip install georeservoir[io]``), and they return data objects that
can contain NaN for missing samples. The engineering functions still refuse NaN, so the
caller selects valid intervals explicitly (``WellLog.valid_mask``).
"""
