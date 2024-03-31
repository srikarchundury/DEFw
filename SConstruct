import os, glob, sysconfig, sys
import distutils.sysconfig

DEFW_PATH = Dir('.').abspath
LIBDEFW_SRC_FILES = glob.glob(os.path.join(DEFW_PATH, "src", "libdefw*.c"))
DEFW_FWSL_FILES = glob.glob(os.path.join(DEFW_PATH, "src", "*.c"))
DEFW_FWSL_FILES = [entry for entry in DEFW_FWSL_FILES if entry not in LIBDEFW_SRC_FILES \
        and 'defw.c' != os.path.basename(entry) and '_wrap' not in entry]

env = Environment()

def generate_swig_intf(source, env):
    cmd = env['PYTHON'] + " " + env['GEN_SWIG_INTF'] + " " + source
    print(cmd)
    os.system(cmd)
    return os.path.splitext(source)[0]+'.i'

def swigify(ifile, target_lib, link_libs, env):
    cmd = env['SWIG'] + " -threads -python -includeall " + env['SWIG_FLAGS'] + " " + env['SWIG_INCLUDES'] + " " + ifile
    print(cmd)
    os.system(cmd)
    wfile = os.path.splitext(ifile)[0]+"_wrap.c"
    cmd = env['CC'] + " " + env['SWIG_COMP_FLAGS'] + " -I" + env['PYTHON_INCLUDE_DIR'] + \
            " -shared " + "-o " + target_lib + \
            " -L" + env['LINK_PATH'] + " " + " ".join(link_libs) + \
            " -L" + env['PYTHON_LIB_DIR'] + " -l" + env['PYTHON_LIB'] + " " + wfile
    print(cmd)
    os.system(cmd)

def build_shared_library(env):
    for cfile in env['LIBDEFW_SRC_FILES']:
        so = os.path.splitext(cfile)[0]+".so"
        cmd = env['CC'] + " " + env['SWIG_COMP_FLAGS'] + " -shared -luuid -o " + so + " " + cfile
        print(cmd)
        os.system(cmd)

def mbuild_shared_library(env, files, so):
    print("building shared library from ", " ".join(files))
    cmd = env['CC'] + " " + env['SWIG_COMP_FLAGS'] + \
            " -I" + env['PYTHON_INCLUDE_DIR'] + \
            " -fPIC -shared -luuid -o " + so + " " + \
            " ".join(files)
    print(cmd)
    os.system(cmd)

def swigify_all_files(env):
    swgs = {}
    for swg in env['DEFW_SWG_FILES']:
        swgs[swg] = ["-l"+os.path.splitext(os.path.basename(swg))[0]]
        if "_agent" in swg:
            swgs[swg].append("-ldefw_connect")

    for k, v in swgs.items():
        ifile = generate_swig_intf(k, env)
        base_name = os.path.basename(ifile)
        lib_name = os.path.join(env['DEFW_PATH'], "src", "_c"+os.path.splitext(base_name)[0]+".so")
        swigify(ifile, lib_name, v, env)

def install(env, src, dst):
    #cmd = "cp " + os.path.join(src, "*.so") + " " + dst
    #print(cmd)
    #os.system(cmd)
    #cmd = "cp " + os.path.join(src, "*.py") + " " + dst
    #print(cmd)
    #os.system(cmd)
    return

def build_bin(env):
    binary = env['DEFW_MAIN_C']
    path = os.path.join(env['DEFW_PATH'], "src", "defwp")
    print("Building standard bin")

    cmd = env['CC'] + " " + env['SWIG_COMP_FLAGS'] + \
            " -I" + env['PYTHON_INCLUDE_DIR'] + " " + \
            binary + " -L" + env['LINK_PATH'] + " -L" + env['PYTHON_LIB_DIR'] + \
            " -lfwsl -ldefw_global -ldefw_connect -ldefw_agent -luuid -l" + env['PYTHON_LIB'] + \
            " -o " + path
    print(cmd)
    os.system(cmd)

def clean(env):
    pfiles = os.path.join(env['DEFW_PATH'], "src", "*.py")
    wfiles = os.path.join(env['DEFW_PATH'], "src", "*_wrap.c")
    ofiles = os.path.join(env['DEFW_PATH'], "src", "*.o")
    ifiles = os.path.join(env['DEFW_PATH'], "src", "*.i")
    cmd = "rm -Rf " + " ".join([pfiles, wfiles, ofiles, ifiles])
    print(cmd)
    os.system(cmd)

print(sys.version)

env['PYTHON'] = "python3"
env['SWIG'] = "swig"
env['SWIG_COMP_FLAGS'] = "-g -Wall -fPIC"
env['SWIG_FLAGS'] = "-D__x86_64__ -D__arch_lib__ -D_LARGEFILE64_SOURCE=1"
env['SWIG_INCLUDES'] = "-I/usr/include -I/usr/include/linux -I/usr/include/x86_64-linux-gnu/"
env['GEN_SWIG_INTF'] = os.path.join('swig_templates', 'generate_swig_i.py')
env['DEFW_PATH'] = DEFW_PATH
env['DEFW_SWG_FILES'] = glob.glob(os.path.join(env['DEFW_PATH'], "src", "*.swg"))
env['LIBDEFW_SRC_FILES'] = LIBDEFW_SRC_FILES
env['DEFW_FWSL_FILES'] = DEFW_FWSL_FILES
env['DEFW_HDR_FILES'] = glob.glob(os.path.join(env['DEFW_PATH'], "src", "*.h"))
env['LINK_PATH'] = os.path.join(env['DEFW_PATH'], "src")
env['PYTHON_INCLUDE_DIR'] = sysconfig.get_config_var('INCLUDEPY')
env['PYTHON_LIB_DIR'] = sysconfig.get_config_var('LIBDIR')
env['PYTHON_LIB'] = os.path.splitext(sysconfig.get_config_var('LDLIBRARY').strip('lib'))[0]
env['DEFW_MAIN_C'] = os.path.join(DEFW_PATH, 'src', 'defw.c')

env.AddMethod(generate_swig_intf)
env.AddMethod(swigify)
env.AddMethod(swigify_all_files)
env.AddMethod(build_shared_library)
env.AddMethod(mbuild_shared_library)
env.AddMethod(install)
env.AddMethod(build_bin)
env.AddMethod(clean)

env.clean_all = env.clean()
env.shared_libs = env.build_shared_library()
env.swigify_files = env.swigify_all_files()
env.fwsl = env.mbuild_shared_library(env['DEFW_FWSL_FILES'], os.path.join(env['DEFW_PATH'], "src", "libfwsl.so"))
env.bin = env.build_bin()
env.install_defw = env.install(os.path.join(env['DEFW_PATH'], "src"),
                              os.path.join(env['DEFW_PATH'], "install"))

Default(env.clean_all, env.shared_libs, env.swigify_files, env.fwsl, env.bin, env.install_defw)

