import importlib.util
import os
import subprocess
import sys

VENDOR_DIRNAME = "_py_deps"
REQUIRED_MODULES = ("numpy", "cv2")
REQUIRED_PACKAGES = ("numpy", "opencv-python-headless")


def get_vendor_path():
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(addon_dir, VENDOR_DIRNAME)


def ensure_vendor_path():
    vendor_path = get_vendor_path()
    if os.path.isdir(vendor_path) and vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    return vendor_path


def dependency_state():
    ensure_vendor_path()
    state = {}
    for module_name in REQUIRED_MODULES:
        state[module_name] = importlib.util.find_spec(module_name) is not None
    return state


def dependencies_installed():
    state = dependency_state()
    return all(state.values())


def _notify(progress_callback, progress, message):
    if progress_callback is not None:
        progress_callback(progress, message)


def install_dependencies(python_executable=None, progress_callback=None):
    vendor_path = get_vendor_path()
    os.makedirs(vendor_path, exist_ok=True)

    if python_executable is None:
        python_executable = sys.executable

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    commands = [
        (
            10.0,
            "Preparing pip environment...",
            [python_executable, "-m", "ensurepip", "--upgrade"],
        ),
        (
            45.0,
            "Installing numpy/opencv...",
            [
                python_executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--target",
                vendor_path,
                *REQUIRED_PACKAGES,
            ],
        ),
    ]

    _notify(progress_callback, 0.0, "Starting dependency installation...")

    logs = []
    for progress, message, cmd in commands:
        _notify(progress_callback, progress, message)
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
        )
        logs.append(
            {
                "command": cmd,
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
        )
        if process.returncode != 0:
            _notify(progress_callback, progress, "Installation failed.")
            return False, logs

    _notify(progress_callback, 85.0, "Verifying installed modules...")
    ensure_vendor_path()
    success = dependencies_installed()
    if success:
        _notify(progress_callback, 100.0, "Installation completed.")
    else:
        _notify(progress_callback, 100.0, "Installation finished, but modules were not detected.")
    return success, logs
