"""Isolated template-toolbox package.

The legacy package initializer eagerly imports unrelated Viv foundation
components. LocalCoder imports only the reviewed submodule requested by its
caller so this candidate remains independently testable.
"""
