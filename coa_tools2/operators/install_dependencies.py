import bpy
import threading

from .. import dependency_manager


def _has_modal_ui(context):
    return (
        not bpy.app.background
        and getattr(context, "window", None) is not None
        and getattr(context, "screen", None) is not None
        and getattr(context, "window_manager", None) is not None
    )


def _new_install_state():
    return {
        "done": False,
        "success": False,
        "logs": [],
        "progress": 0.0,
        "status_message": "Starting dependency installation...",
    }


def _make_progress_callback(state):
    def progress_callback(progress, message):
        state["progress"] = max(0.0, min(100.0, float(progress)))
        state["status_message"] = str(message)

    return progress_callback


def _print_failed_install_log(logs):
    failed_log = None
    for log in logs:
        if log["returncode"] != 0:
            failed_log = log
            break

    if failed_log is None:
        return

    print("COA Tools2 dependency install failed:")
    print("Command:", " ".join(failed_log["command"]))
    if failed_log["stdout"]:
        print(failed_log["stdout"])
    if failed_log["stderr"]:
        print(failed_log["stderr"])


def _exception_log(exc):
    return [
        {
            "command": ["dependency-install"],
            "returncode": 1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }
    ]


class COATOOLS2_OT_InstallPythonDependencies(bpy.types.Operator):
    bl_idname = "coa_tools2.install_python_dependencies"
    bl_label = "Install numpy / opencv"
    bl_description = "Install optional Automesh dependencies into Blender Python"
    bl_options = {"REGISTER"}

    _is_running = False

    @classmethod
    def poll(cls, context):
        return not cls._is_running

    def _install_worker(self, state):
        try:
            success, logs = dependency_manager.install_dependencies(
                progress_callback=_make_progress_callback(state)
            )
        except Exception as exc:
            success = False
            logs = _exception_log(exc)
            state["status_message"] = "Installation failed."

        state["success"] = success
        state["logs"] = logs
        state["done"] = True

    def _finish_install(self, success, logs):
        if success:
            self.report(
                {"INFO"},
                "Installed numpy/opencv. Re-enable addon or restart Blender.",
            )
            return {"FINISHED"}

        _print_failed_install_log(logs)
        self.report(
            {"WARNING"} if bpy.app.background else {"ERROR"},
            "Dependency installation failed. Existing numpy/cv2 may be incompatible. See system console.",
        )
        return {"CANCELLED"}

    def _run_sync(self):
        state = _new_install_state()
        try:
            success, logs = dependency_manager.install_dependencies(
                progress_callback=_make_progress_callback(state)
            )
        except Exception as exc:
            success = False
            logs = _exception_log(exc)
        return self._finish_install(success, logs)

    def _start_modal(self, context):
        COATOOLS2_OT_InstallPythonDependencies._is_running = True
        state = _new_install_state()
        self._install_state = state

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)

        self._thread = threading.Thread(
            target=self._install_worker, args=(state,), daemon=True
        )
        self._thread.start()

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if COATOOLS2_OT_InstallPythonDependencies._is_running:
            self.report({"WARNING"}, "Dependency installation is already running.")
            return {"CANCELLED"}
        if not _has_modal_ui(context):
            return self._run_sync()
        self._start_modal(context)
        return context.window_manager.invoke_popup(self, width=460)

    def execute(self, context):
        if COATOOLS2_OT_InstallPythonDependencies._is_running:
            self.report({"WARNING"}, "Dependency installation is already running.")
            return {"CANCELLED"}
        return self._run_sync()

    def draw(self, context):
        state = getattr(self, "_install_state", _new_install_state())
        layout = self.layout
        layout.label(text="Installing numpy/opencv in Blender Python...")
        layout.label(text=f"Progress: {int(state['progress'])}%")
        layout.label(text=state["status_message"])
        if not state["done"]:
            layout.label(text="This window closes automatically when done.", icon="INFO")

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        state = getattr(self, "_install_state", None)
        if state is None:
            COATOOLS2_OT_InstallPythonDependencies._is_running = False
            return {"CANCELLED"}

        wm = context.window_manager
        wm.progress_update(int(state["progress"]))

        # refresh UI while popup is visible
        for area in context.screen.areas:
            area.tag_redraw()

        if not state["done"]:
            return {"PASS_THROUGH"}

        wm.progress_end()
        wm.event_timer_remove(self._timer)
        COATOOLS2_OT_InstallPythonDependencies._is_running = False

        return self._finish_install(state["success"], state["logs"])
