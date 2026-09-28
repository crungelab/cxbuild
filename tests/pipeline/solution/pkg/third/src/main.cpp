#define PY_SSIZE_T_CLEAN
// MSVC Debug builds define _DEBUG, and pyconfig.h then links the debug Python
// library (python3xx_d.lib), which most installs don't have. Hide _DEBUG from
// Python.h unless this really is a debug Python (the same trick pybind11 uses).
#if defined(_MSC_VER) && defined(_DEBUG) && !defined(Py_DEBUG)
#  undef _DEBUG
#  include <Python.h>
#  define _DEBUG
#else
#  include <Python.h>
#endif

static PyObject* triple(PyObject*, PyObject* args) {
    long x;
    if (!PyArg_ParseTuple(args, "l", &x)) return nullptr;
    return PyLong_FromLong(3 * x);
}

static PyMethodDef methods[] = {
    {"triple", triple, METH_VARARGS, "Multiply by three."},
    {nullptr, nullptr, 0, nullptr},
};

static PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT, "_core", "cxbns.third: cxbuild pipeline-test module", -1, methods,
};

PyMODINIT_FUNC PyInit__core() { return PyModule_Create(&module_def); }
