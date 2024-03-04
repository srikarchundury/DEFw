#include <Python.h>
#include <netinet/in.h>
#include <stdatomic.h>
#include "defw.h"
#include "defw_python.h"
#include "defw_listener.h"

extern defw_config_params_t g_defw_cfg;
static PyObject *g_interactive_shell;
static pthread_mutex_t g_interactive_shell_mutex;
static atomic_long g_py_gil_refcount;

#define RUN_PYTHON_CMD(cmd) {\
	int py_rc;							\
	py_rc = PyRun_SimpleString(cmd);				\
	if (py_rc) {							\
		PERROR("Python execution failed: %d", py_rc);		\
		return EN_DEFW_RC_PY_SCRIPT_FAIL;			\
	}								\
}

#define RUN_PYTHON_CMD_OBJ(cmd, obj, globals, locals) {			\
	PyObject *type, *value, *traceback, *str_value;			\
	obj = PyRun_String(cmd, 0, globals, locals);			\
	if (!obj) {							\
		PERROR("Python cmd failed: %s", cmd);			\
		PyErr_Fetch(&type, &value, &traceback);			\
		PERROR("Exception type: %s", Py_TYPE(type)->tp_name);	\
		str_value = PyObject_Str(value);			\
		if (str_value)						\
			printf("Exception value: %s",			\
			       PyUnicode_AsUTF8(str_value));		\
		return EN_DEFW_RC_PY_SCRIPT_FAIL;			\
	}								\
}

defw_rc_t python_exec(char *code)
{
	RUN_PYTHON_CMD(code);
	return EN_DEFW_RC_OK;
}

static defw_rc_t python_setup(void)
{
	char buf[MAX_STR_LEN * 4];
	char cwd[MAX_STR_LEN];
	char *infra = getenv(DEFW_PATH);

	if (!infra) {
		if (getcwd(cwd, sizeof(cwd)) != NULL) {
			PDEBUG("Current working directory: %s", cwd);
		} else {
			PERROR("getcwd");
			exit(DEFW_EXIT_ERR_STARTUP);
		}
		infra = cwd;
	}

	RUN_PYTHON_CMD("import code\n");
	RUN_PYTHON_CMD("import os\n");
	RUN_PYTHON_CMD("import sys\n");
	RUN_PYTHON_CMD("import readline\n");
/*
	snprintf(buf, sizeof(buf),
		"import sys\n"
		"import traceback\n"
		"def log_exception(exc_type, exc_value, exc_traceback):\n"
		"    with open('/tmp/defwtmp', 'a') as f:\n"
		"        f.write(f\"Exception Type: {exc_type}\\n\")\n"
		"        f.write(f\"Exception Value: {exc_value}\\n\")\n"
		"        f.write(\"Traceback:\\n\")\n"
		"        f.writelines(traceback.format_exception(exc_type, exc_value, exc_traceback))\n"
		"sys.excepthook = log_exception");
	RUN_PYTHON_CMD(buf);
*/
	/* all other paths are figured out within python */
	snprintf(buf, sizeof(buf),
		"sys.path.append(os.path.join('%s', 'python', 'infra'))", infra);
	RUN_PYTHON_CMD(buf);
	snprintf(buf, sizeof(buf),
		"sys.path.append(os.path.join('%s', 'src'))", infra);
	RUN_PYTHON_CMD(buf);

	snprintf(buf, sizeof(buf),
		 "f = open('/tmp/ashehata', 'a'); f.write(str(sys.path)); f.close()");
	RUN_PYTHON_CMD(buf);

	RUN_PYTHON_CMD("import defw\n");
	RUN_PYTHON_CMD("from defw import me,experiments,"
		"services,service_apis,client_agents,service_agents,"
		"active_client_agents,active_service_agents,"
		"resmgr,dumpGlobalTestResults,R,C,S,AC,AS,I,X\n"
		"from defw_workers import worker_thread\n");

	return EN_DEFW_RC_OK;
}

defw_rc_t python_run_interactive_shell(void)
{
	char *intro;
	PyObject *globals, *main;

	PDEBUG("Running in Interactive mode");
	/*
	 * start an independent shell
	 * Since we imported all the necessary modules to start in
	 * the main interpreter, copying the globals should copy
	 * them in the interactive shell.
	 */
	RUN_PYTHON_CMD("vars = globals().copy()\n");
	RUN_PYTHON_CMD("vars.update(locals())\n");
	RUN_PYTHON_CMD("shell = code.InteractiveConsole(vars)\n");
	main = PyImport_AddModule("__main__");
	globals = PyModule_GetDict(main);
	g_interactive_shell = PyDict_GetItemString(globals, "shell");
	//Py_DECREF(main);
	//Py_DECREF(globals);
	RUN_PYTHON_CMD("shell.push('sys.ps1 = \"defw>>> \"')\n");
	RUN_PYTHON_CMD("shell.push('sys.ps2 = \"defw... \"')\n");

	/* import base defw module */
	g_defw_cfg.initialized = true;

	intro = "shell.interact('Welcome to the Distributed Execution Framework (DEFw)\\n"
		"Convenience Functions: \\n"
		"\tR() = dumpGlobalTestResults()\\n"
		"\tS() = services.dump()\\n"
		"\tC() = clients.dump()\\n"
		"\tAS() = active_services.dump()\\n"
		"\tAC() = active_clients.dump()\\n"
		"\tI() = me.dump_intfs()\\n"
		"\tX() = me.exit()\\n"
		"Convenience Objects: \\n"
		"\\tme - Instance of this ISL\\n"
		"\\texperiments - All experiment scripts\\n"
		"\\tservices - Available services to offer\\n"
		"\\tservice_apis - Available service interface APIs\\n')";
	RUN_PYTHON_CMD(intro);

	return EN_DEFW_RC_OK;
}

defw_rc_t python_run_cmd_line(int argc, char *argv[], char *module, char *cmd)
{
	char buf[MAX_STR_LEN * 4];
	PyObject *pSysArgv;
	PyObject *pArg;
	ssize_t len;
	FILE *f;

	if (!g_defw_cfg.initialized)
		return EN_DEFW_RC_PY_SCRIPT_FAIL;

	/* skip the option */
	if (module) {
		argc -= 1;
		argv += 1;
	/* skip the option and its arg */
	} else if (cmd) {
		argc -= 2;
		argv += 2;
	}

	pSysArgv = PySys_GetObject("argv");
	for (int i = 0; i < argc; ++i) {
		pArg = PyUnicode_DecodeUTF8(argv[i], strlen(argv[i]), "surrogateescape");
		PyList_Append(pSysArgv, pArg);
		Py_DECREF(pArg);
	}
	len = readlink("/proc/self/exe", buf, sizeof(buf)-1);
	if (len < sizeof(buf)-1)
		buf[len] = '\0';
	else
		buf[sizeof(buf)-1] = '\0';

	PySys_SetObject("executable", PyUnicode_DecodeFSDefault(buf));
	PySys_SetObject("_base_executable", PyUnicode_DecodeFSDefault(buf));

	RUN_PYTHON_CMD("sys.argv.pop(0); print(sys.argv)\n");

	if (module) {
		sprintf(buf,
			"import runpy\n"
			"try:\n"
			"    runpy.run_module('%s', run_name='__main__', alter_sys=False)\n"
			"except SystemExit as e:\n"
			"    pass\n"
			"except Exception as e:\n"
			"    print(e)\n"
			"print(f'Running module %s with args: {sys.argv}')\n", module, module);
		RUN_PYTHON_CMD(buf);
	} else if (cmd) {
		RUN_PYTHON_CMD(cmd);
	} else if (argc >= 1) {
		f = fopen(argv[0], "r");
		if (!f)
			return EN_DEFW_RC_PY_SCRIPT_FAIL;

		PyRun_SimpleFile(f, argv[0]);
		fclose(f);
	}

	return EN_DEFW_RC_OK;
}

/*
 * gcc py.c -o py -I/usr/local/include/python2.7
 * -L/usr/local/lib/python2.7/config -lm -ldl -lpthread -lutil -lpython2.7
 */
defw_rc_t python_init(void)
{
	wchar_t program[5];

	pthread_mutex_init(&g_interactive_shell_mutex, NULL);
	atomic_init(&g_py_gil_refcount, 0);

	swprintf(program, 3, L"%hs", "defw");

	Py_SetProgramName(program);

	Py_Initialize();

	return python_setup();
}

defw_rc_t python_finalize()
{
	PDEBUG("Python finalizing");

	if (g_defw_cfg.shell == EN_DEFW_RUN_CMD_LINE)
		RUN_PYTHON_CMD("me.exit()")
	Py_Finalize();

	PDEBUG("Python finalized");

	return EN_DEFW_RC_OK;
}

typedef enum python_callbacks {
	EN_PY_CB_REQUEST,
	EN_PY_CB_RESPONSE,
	EN_PY_CB_REFRESH,
	EN_PY_CB_CONNECT,
	EN_PY_CB_MAX,
} python_callbacks_t;

char *python_callback_str[EN_PY_CB_MAX] = {
	"put_request",
	"put_response",
	"put_refresh",
	"put_connect_complete",
};

PyGILState_STATE python_gil_ensure()
{
	PyGILState_STATE gstate;
	gstate = PyGILState_Ensure();
	(void)atomic_fetch_add(&g_py_gil_refcount, 1);
	return gstate;
}

void python_gil_release(PyGILState_STATE gstate)
{
	PyGILState_Release(gstate);
	(void) atomic_fetch_sub(&g_py_gil_refcount, 1);
}

static defw_rc_t
python_handle_op(char *msg, defw_rc_t status, char *uuid, python_callbacks_t cb)
{
	defw_rc_t rc = EN_DEFW_RC_OK;
	PyGILState_STATE gstate;
	PyObject *py_handler;
	PyObject *defw;
	PyObject *str;
	PyObject *args = NULL;
	PyObject *result;
	char *func = python_callback_str[cb];

	if (!g_defw_cfg.initialized)
		return EN_DEFW_RC_PY_SCRIPT_FAIL;

	if (msg && uuid)
		PMSG("Handling %s from %s\n%s", func, uuid, msg);

	gstate = python_gil_ensure();

	str = PyUnicode_FromString((char *)"defw_workers");
	defw = PyImport_Import(str);
	py_handler = PyObject_GetAttrString(defw, func);
	switch (cb) {
	/* All strings passed to python via the CPython API are now owned
	 * and managed by python. No need to free them.
	 */
	case EN_PY_CB_REQUEST:
	case EN_PY_CB_RESPONSE:
		args = PyTuple_Pack(2, PyUnicode_FromString(msg),
				PyUnicode_FromString(uuid));
		break;
	case EN_PY_CB_CONNECT:
		args = PyTuple_Pack(2, PyLong_FromLong((long)status),
				    PyUnicode_FromString(uuid));
		break;
	default:
		break;
	}

	result = PyObject_CallObject(py_handler, args);

	if (!result)
		PDEBUG("%s didn't return any values", func);

	python_gil_release(gstate);

	return rc;
}

defw_rc_t python_handle_request(char *msg, char *uuid)
{
	return python_handle_op(msg, EN_DEFW_RC_OK, uuid, EN_PY_CB_REQUEST);
}

defw_rc_t python_handle_response(char *msg, char *uuid)
{
	return python_handle_op(msg, EN_DEFW_RC_OK, uuid, EN_PY_CB_RESPONSE);
}

defw_rc_t python_refresh_agent(void)
{
	return python_handle_op(NULL, EN_DEFW_RC_OK, NULL, EN_PY_CB_REFRESH);
}

defw_rc_t python_handle_connect_complete(defw_rc_t status, char *uuid)
{
	return python_handle_op(NULL, status, uuid, EN_PY_CB_CONNECT);
}

void python_update_interactive_shell(void)
{
//	PyGILState_STATE gstate;
//	PyObject *defw, *globals, *locals, *globals_copy;
	/*
	PyObject *key, *value;
	Py_ssize_t pos = 0;
	*/

//	if (!g_interactive_shell)
//		return;

//	fprintf(stderr, "Updating interactive shell\n");

//	pthread_mutex_lock(&g_interactive_shell_mutex);
//	gstate = python_gil_ensure();
//	defw = PyImport_AddModule("defw");
//	globals = PyModule_GetDict(defw);
	/*
	while (PyDict_Next(globals, &pos, &key, &value)) {
		printf("Key: %s\n", PyUnicode_AsUTF8(key));
		printf("Value (str): %s\n", PyUnicode_AsUTF8(PyObject_Str(value)));
	}
	*/
//	locals = PyObject_GetAttrString(g_interactive_shell, "locals");
//	globals_copy = PyDict_Copy(globals);
//	PyDict_Update(locals, globals_copy);
//	Py_DECREF(defw);
//	Py_DECREF(locals);
//	Py_DECREF(globals);
//	Py_DECREF(globals_copy);
	// TODO: Causes interactive shell to exit. Not sure if it's even
	// needed at this point
	//Py_DECREF(g_interactive_shell);
//	python_gil_release(gstate);
//	pthread_mutex_unlock(&g_interactive_shell_mutex);
}

