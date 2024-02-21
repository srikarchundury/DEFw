#include <Python.h>
#include <netinet/in.h>
#include "defw.h"
#include "defw_python.h"
#include "defw_listener.h"

extern defw_config_params_t g_defw_cfg;
static PyObject *g_interactive_shell;
static pthread_mutex_t g_interactive_shell_mutex;

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
	char buf[MAX_STR_LEN + 20];
	char cwd[MAX_STR_LEN];
	char *infra = getenv(IFW_PATH);

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

	/* all other paths are figured out within python */
	snprintf(buf, sizeof(buf),
		"sys.path.append(os.path.join('%s', 'python', 'infra'))", infra);
	RUN_PYTHON_CMD(buf);
	snprintf(buf, sizeof(buf),
		"sys.path.append(os.path.join('%s', 'src'))", infra);
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
	intro = "shell.interact('Welcome to the Intersect Framework (IFW)\\n"
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

defw_rc_t python_run_cmd_line(int argc, char *argv[])
{
	int py_rc;

	// Convert char* command-line arguments to wchar_t*
	wchar_t** wideArgv = (wchar_t**)malloc((argc + 1) * sizeof(wchar_t*));
	for (int i = 0; i < argc; ++i) {
		int wideArgc = mbstowcs(NULL, argv[i], 0);
		wideArgv[i] = (wchar_t*)malloc((wideArgc + 1) * sizeof(wchar_t));
		mbstowcs(wideArgv[i], argv[i], wideArgc + 1);
	}
	wideArgv[argc] = NULL;

	py_rc = Py_Main(argc, wideArgv);
	free(wideArgv);
	if (py_rc) {
		PERROR("Python execution failed: %d\n", py_rc);
		return EN_DEFW_RC_PY_SCRIPT_FAIL;
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

	swprintf(program, 3, L"%hs", "defw");

	Py_SetProgramName(program);

	Py_Initialize();

	return python_setup();
}

void python_finalize()
{
	PDEBUG("Python finalizing");

	Py_Finalize();

	PDEBUG("Python finalized");
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

	gstate = PyGILState_Ensure();

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

	PyGILState_Release(gstate);

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
	PyGILState_STATE gstate;
	PyObject *defw, *globals, *locals, *globals_copy;
	/*
	PyObject *key, *value;
	Py_ssize_t pos = 0;
	*/

	if (!g_interactive_shell)
		return;

	pthread_mutex_lock(&g_interactive_shell_mutex);
	gstate = PyGILState_Ensure();
	defw = PyImport_AddModule("defw");
	globals = PyModule_GetDict(defw);
	/*
	while (PyDict_Next(globals, &pos, &key, &value)) {
		printf("Key: %s\n", PyUnicode_AsUTF8(key));
		printf("Value (str): %s\n", PyUnicode_AsUTF8(PyObject_Str(value)));
	}
	*/
	locals = PyObject_GetAttrString(g_interactive_shell, "locals");
	globals_copy = PyDict_Copy(globals);
	PyDict_Update(locals, globals_copy);
	Py_DECREF(defw);
	Py_DECREF(locals);
	Py_DECREF(globals);
	Py_DECREF(globals_copy);
	Py_DECREF(g_interactive_shell);
	PyGILState_Release(gstate);
	pthread_mutex_unlock(&g_interactive_shell_mutex);
}

