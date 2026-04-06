import importlib
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
    state, _ = dependency_state_with_errors()
    return state


def dependencies_installed():
    state = dependency_state()
    return all(state.values())


def _try_import(module_name):
    try:
        importlib.import_module(module_name)
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def dependency_state_with_errors():
    ensure_vendor_path()
    state = {}
    errors = {}
    for module_name in REQUIRED_MODULES:
        is_ok, error = _try_import(module_name)
        state[module_name] = is_ok
        if not is_ok:
            errors[module_name] = error
    return state, errors


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

    logs = []

    _notify(progress_callback, 0.0, "Checking existing dependencies...")
    state_before, errors_before = dependency_state_with_errors()
    if all(state_before.values()):
        logs.append(
            {
                "command": ["dependency-check"],
                "returncode": 0,
                "stdout": "numpy/cv2 already importable.",
                "stderr": "",
            }
        )
        _notify(progress_callback, 100.0, "Dependencies already installed.")
        return True, logs

    logs.append(
        {
            "command": ["dependency-check"],
            "returncode": 1,
            "stdout": "",
            "stderr": "\n".join(
                f"{module}: {error}" for module, error in errors_before.items()
            ),
        }
    )

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
                "--force-reinstall",
                "--no-cache-dir",
                "--target",
                vendor_path,
                *REQUIRED_PACKAGES,
            ],
        ),
    ]

    _notify(progress_callback, 5.0, "Starting dependency installation...")
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
            state_after_failure, errors_after_failure = dependency_state_with_errors()
            if all(state_after_failure.values()):
                _notify(
                    progress_callback,
                    100.0,
                    "Install command failed, but dependencies are available.",
                )
                return True, logs

            logs.append(
                {
                    "command": ["dependency-check"],
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "\n".join(
                        f"{module}: {error}"
                        for module, error in errors_after_failure.items()
                    ),
                }
            )
            _notify(progress_callback, progress, "Installation failed.")
            return False, logs

    _notify(progress_callback, 85.0, "Verifying installed modules...")
    ensure_vendor_path()
    state_after_install, errors_after_install = dependency_state_with_errors()
    success = all(state_after_install.values())
    if success:
        _notify(progress_callback, 100.0, "Installation completed.")
    else:
        logs.append(
            {
                "command": ["dependency-check"],
                "returncode": 1,
                "stdout": "",
                "stderr": "\n".join(
                    f"{module}: {error}" for module, error in errors_after_install.items()
                ),
            }
        )
        _notify(progress_callback, 100.0, "Installation finished, but modules were not detected.")
    return success, logs
