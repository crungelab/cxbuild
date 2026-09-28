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

static PyObject* add(PyObject*, PyObject* args) {
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b)) return nullptr;
    return PyLong_FromLong(a + b);
}

static PyMethodDef methods[] = {
    {"add", add, METH_VARARGS, "Add two integers."},
    {nullptr, nullptr, 0, nullptr},
};

static PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT, "_core", "cxb_simple: cxbuild pipeline-test module", -1, methods,
};

PyMODINIT_FUNC PyInit__core() { return PyModule_Create(&module_def); }
