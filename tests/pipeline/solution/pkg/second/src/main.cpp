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

static PyObject* greet(PyObject*, PyObject* args) {
    const char* name;
    if (!PyArg_ParseTuple(args, "s", &name)) return nullptr;
    return PyUnicode_FromFormat("hello, %s", name);
}

static PyMethodDef methods[] = {
    {"greet", greet, METH_VARARGS, "Greet someone."},
    {nullptr, nullptr, 0, nullptr},
};

static PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT, "_core", "cxbns.second: cxbuild pipeline-test module", -1, methods,
};

PyMODINIT_FUNC PyInit__core() { return PyModule_Create(&module_def); }
